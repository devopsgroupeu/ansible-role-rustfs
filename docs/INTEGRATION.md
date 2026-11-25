# Integration Guide

How to consume the `devopsgroupeu.rustfs` role in other projects, what to
prepare on the hosts before it runs, and how to wire the S3 service it
produces into the rest of a platform.

---

## Table of Contents

- [Consuming the role via requirements.yml](#consuming-the-role-via-requirementsyml)
- [Preparing the drives](#preparing-the-drives)
- [BYO certificates](#byo-certificates)
- [HAProxy in front of the cluster](#haproxy-in-front-of-the-cluster)
- [S3 clients](#s3-clients)
- [Terraform](#terraform)
- [Loki](#loki)
- [Velero](#velero)
- [Prometheus metrics through an OpenTelemetry Collector](#prometheus-metrics-through-an-opentelemetry-collector)
- [Server-side encryption with OpenBao Transit](#server-side-encryption-with-openbao-transit)
- [Mirrors and egress](#mirrors-and-egress)
- [Post-role workflow](#post-role-workflow)

---

## Consuming the role via requirements.yml

### From Ansible Galaxy

```yaml
# requirements.yml in the consuming project
collections:
  - name: community.crypto
    version: ">=3.2.2"

roles:
  - name: devopsgroupeu.rustfs
    version: "X.Y.Z"   # latest release, see GitHub Releases
```

Install:

```bash
ansible-galaxy collection install -r requirements.yml
ansible-galaxy role install -r requirements.yml
```

### From Git source

```yaml
# requirements.yml - git source
roles:
  - name: devopsgroupeu.rustfs
    src: https://github.com/devopsgroupeu/ansible-role-rustfs.git
    version: "vX.Y.Z"   # a release tag (latest: see GitHub Releases) or a commit SHA
    scm: git
```

Install:

```bash
ansible-galaxy role install -r requirements.yml -p roles/
```

The consuming playbook must have the install directory on its roles path
(`roles_path` in `ansible.cfg`, or `ANSIBLE_ROLES_PATH`).

---

## Preparing the drives

The role does not partition, format or mount drives; it refuses to continue
until every data dir is a mount point (`rustfs_require_mounted_drives`).
Prepare them in `pre_tasks`, one XFS filesystem per physical disk, mounted
by UUID with `nofail` (a dead disk must not block the boot; the RustFS unit
refuses to start until the drive is back). This snippet uses
`community.general` and `ansible.posix`, which the role itself does not
need:

```yaml
- name: Deploy RustFS
  hosts: rustfs
  become: true
  vars:
    # Device per data dir; same paths and labels on every node.
    storage_drives:
      - {device: /dev/sdb, path: /data/rustfs0, label: RUSTFS0}
      - {device: /dev/sdc, path: /data/rustfs1, label: RUSTFS1}
      - {device: /dev/sdd, path: /data/rustfs2, label: RUSTFS2}
      - {device: /dev/sde, path: /data/rustfs3, label: RUSTFS3}
  pre_tasks:
    # Creates a filesystem only where none exists (no force).
    - name: Format the RustFS drives with XFS
      community.general.filesystem:
        dev: "{{ item['device'] }}"
        fstype: xfs
        opts: "-i size=512 -n ftype=1 -L {{ item['label'] }}"
      loop: "{{ storage_drives }}"
      loop_control:
        label: "{{ item['device'] }}"

    - name: Read the filesystem UUIDs
      ansible.builtin.command:
        argv: [blkid, -s, UUID, -o, value, "{{ item['device'] }}"]
      loop: "{{ storage_drives }}"
      loop_control:
        label: "{{ item['device'] }}"
      register: storage_uuids
      changed_when: false

    - name: Mount the RustFS drives by UUID
      ansible.posix.mount:
        path: "{{ item['item']['path'] }}"
        src: "UUID={{ item['stdout'] }}"
        fstype: xfs
        opts: defaults,noatime,nodiratime,nofail
        state: mounted
      loop: "{{ storage_uuids['results'] }}"
      loop_control:
        label: "{{ item['item']['path'] }}"
  roles:
    - role: devopsgroupeu.rustfs
```

Rules from upstream: XFS (RustFS is developed and tested on it), no hardware
RAID, no LVM or partitions that put two data dirs on one disk (RustFS
refuses that at startup), no NFS, and never a data dir that contains another
mount point. The role sets `rustfs:rustfs 0750` on each mount point only,
never recursively.

---

## BYO certificates

With the default `rustfs_tls_enabled: true` and
`rustfs_tls_generate_certs: false`, the role expects three files in
`rustfs_tls_dir` (`/etc/rustfs/tls`) before it runs and never creates them:

| File | Content |
|---|---|
| `rustfs_cert.pem` | the node certificate, full chain, leaf first; SAN for `rustfs_node_address` (in a cluster: the node's host name in `rustfs_volumes`), EKU serverAuth |
| `rustfs_key.pem` | its private key |
| `ca.crt` | the CA that signed every node certificate (not needed with `rustfs_tls_trust_system_ca: true`) |

Place them in `pre_tasks`, for example from files encrypted with
`ansible-vault` next to the playbook. The service group does not exist
before the first run, so copy the key as `root:root 0600`; the role then
sets it to `root:rustfs 0640` and the certificate and CA to
`root:root 0644`:

```yaml
  pre_tasks:
    - name: Create the RustFS TLS directory
      ansible.builtin.file:
        path: /etc/rustfs/tls
        state: directory
        owner: root
        group: root
        mode: "0750"

    - name: Place the node certificate, key and CA
      ansible.builtin.copy:
        src: "{{ item['src'] }}"
        dest: "/etc/rustfs/tls/{{ item['dest'] }}"
        owner: root
        group: root
        mode: "{{ item['mode'] }}"
      loop:
        - {src: "files/tls/{{ inventory_hostname }}.crt", dest: rustfs_cert.pem, mode: "0644"}
        - {src: "files/tls/{{ inventory_hostname }}.key", dest: rustfs_key.pem, mode: "0600"}
        - {src: files/tls/ca.crt, dest: ca.crt, mode: "0644"}
      loop_control:
        label: "{{ item['dest'] }}"
      no_log: true
```

RustFS reloads replaced files within 30 s, so a renewal is just this
pre-task with new files: the role checks validity, SANs and the key match
and restarts nothing.

---

## HAProxy in front of the cluster

Clients can use any node, but a load balancer gives them one name and keeps
traffic away from a node while it restarts. With
[ansible-role-haproxy-keepalived](https://github.com/devopsgroupeu/ansible-role-haproxy-keepalived),
terminate TLS on the VIP and re-encrypt to the nodes:

```yaml
# group_vars of the proxy hosts
haproxy_frontends:
  - name: rustfs_s3
    address: "*"
    port: 443
    mode: http
    ssl: true
    crts:
      - /etc/haproxy/certs/s3.example.com.pem
    default_backend: rustfs_s3

haproxy_backends:
  - name: rustfs_s3
    mode: http
    balance: leastconn
    http_check:
      send:
        method: GET
        uri: /health/ready
      expect: status 200
    servers: "{{ groups['rustfs'] }}"
    port: 9000
    options:
      - check
      - inter 5s
      - fall 2
      - rise 2
      - ssl
      - verify required
      - ca-file /etc/haproxy/rustfs-ca.crt

# Large single-request uploads: allow long transfers.
haproxy_timeout_client: 5m
haproxy_timeout_server: 5m
```

Rules from upstream (`docs/operations/reverse-proxy.md`):

- Health-check `/health/ready` (200 only when the node can serve reads), not
  `/health/live`.
- Keep the proxy's idle keep-alive towards RustFS below RustFS's
  `RUSTFS_HTTP1_HEADER_READ_TIMEOUT` (75 s); otherwise the proxy reuses
  connections RustFS has closed and large uploads fail with
  `socket hang up`. HAProxy purges idle server connections after `pool-purge-delay`
  (5 s by default).
- Do not compress, buffer or re-chunk request bodies, do not rewrite `Host`
  or `x-amz-*` headers (SigV4 signs them), and do not strip `ETag`.
- RustFS honours `X-Forwarded-For` only from trusted proxies (loopback by
  default). Add the proxy addresses so access logs and policies see the
  client IP:

  ```yaml
  # group_vars/rustfs
  rustfs_extra_env:
    RUSTFS_TRUSTED_PROXY_EXTRA_NETWORKS: "192.0.2.5/32,192.0.2.6/32"
  ```

The proxy certificate covers the public name (`s3.example.com`); the node
certificates cover the node names. HAProxy above verifies the node chain
against the private CA. For virtual-hosted-style requests through the VIP
set `rustfs_server_domains: ["s3.example.com"]` and add the wildcard name
to the proxy certificate and DNS.

---

## S3 clients

RustFS speaks S3 on port 9000 (or the VIP). Use dedicated IAM users or
service accounts for applications, never the root keys
([Post-role workflow](#post-role-workflow)).

### aws CLI

```bash
export AWS_ACCESS_KEY_ID=<access key> AWS_SECRET_ACCESS_KEY=<secret key>
export AWS_DEFAULT_REGION=us-east-1
aws configure set default.s3.addressing_style path

aws --endpoint-url https://s3.example.com --ca-bundle /path/to/ca.crt s3 mb s3://backups
aws --endpoint-url https://s3.example.com --ca-bundle /path/to/ca.crt s3 cp ./file s3://backups/
```

### rc (RustFS client)

`rc` is the first-party client for S3 and the RustFS admin API (users,
policies, pools, healing). It is not installed by the role. Install a
pinned release from <https://github.com/rustfs/cli/releases> and check it
against the release's `SHA256SUMS`, then:

```bash
rc alias set prod https://s3.example.com <access key> <secret key>
rc ready prod
rc admin info cluster prod
rc bucket list prod/
```

`rc alias set` writes the credentials into the user's `rc` configuration;
run it on an operator workstation, not in a shared CI job log.

### Path-style or virtual-hosted-style

Without `rustfs_server_domains` RustFS answers path-style requests only
(`https://s3.example.com/bucket/key`). AWS SDKs and Terraform default to
virtual-hosted style (`https://bucket.s3.example.com/key`): either switch
the client to path style (`s3_use_path_style`, `s3ForcePathStyle`,
`forcePathStyle`), or set `rustfs_server_domains: ["s3.example.com"]` and
add wildcard DNS and a wildcard certificate for `*.s3.example.com`.

---

## Terraform

Buckets, versioning, lifecycle and bucket policies belong in Terraform with
the `hashicorp/aws` provider pointed at RustFS. The provider cannot manage
RustFS IAM users and policies (RustFS documents no AWS IAM API); manage
those with `rc admin` or the console.

```hcl
provider "aws" {
  alias                       = "rustfs"
  region                      = "us-east-1"
  access_key                  = var.rustfs_access_key
  secret_key                  = var.rustfs_secret_key
  s3_use_path_style           = true
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true

  endpoints {
    s3 = "https://s3.example.com"
  }
}

resource "aws_s3_bucket" "loki" {
  provider = aws.rustfs
  bucket   = "loki-chunks"
}

resource "aws_s3_bucket_versioning" "loki" {
  provider = aws.rustfs
  bucket   = aws_s3_bucket.loki.id
  versioning_configuration {
    status = "Enabled"
  }
}
```

As a Terraform state backend (Terraform >= 1.11 for `use_lockfile`; RustFS
1.0.6 accepts the conditional `If-None-Match: *` write it relies on):

```hcl
terraform {
  backend "s3" {
    bucket                      = "terraform-state"
    key                         = "platform/terraform.tfstate"
    region                      = "us-east-1"
    endpoints                   = { s3 = "https://s3.example.com" }
    use_path_style              = true
    use_lockfile                = true
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
  }
}
```

Pass the credentials through `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
(or `-backend-config`), never in the file. A private CA must be trusted by
the machine that runs Terraform (`AWS_CA_BUNDLE=/path/to/ca.crt`).

---

## Loki

Loki stores chunks and the TSDB index in one bucket. Single-binary or
Helm-rendered configuration, `common.storage.s3` block:

```yaml
common:
  storage:
    s3:
      endpoint: s3.example.com:443
      insecure: false
      bucketnames: loki-chunks
      region: us-east-1
      access_key_id: ${LOKI_S3_ACCESS_KEY}
      secret_access_key: ${LOKI_S3_SECRET_KEY}
      s3forcepathstyle: true
      http_config:
        ca_file: /etc/loki/rustfs-ca.crt
```

`${...}` needs Loki's `-config.expand-env=true`. `endpoint` is
`host:port` without a scheme; `insecure: false` selects HTTPS.

---

## Velero

Velero uses its AWS object store plugin. Create the bucket first (Velero
does not):

```yaml
apiVersion: velero.io/v1
kind: BackupStorageLocation
metadata:
  name: default
  namespace: velero
spec:
  provider: aws
  objectStorage:
    bucket: velero-backups
    caCert: <base64 of the private CA certificate>
  config:
    region: us-east-1
    s3ForcePathStyle: "true"
    s3Url: https://s3.example.com
  credential:
    name: cloud-credentials
    key: cloud
```

The `cloud-credentials` secret holds an AWS credentials file
(`[default]`, `aws_access_key_id=...`, `aws_secret_access_key=...`) of a
dedicated IAM user. `s3Url` must be reachable from the pods, not only from
your workstation.

---

## Prometheus metrics through an OpenTelemetry Collector

RustFS has no Prometheus scrape endpoint. It pushes metrics, traces and logs
over OTLP/HTTP; run an OpenTelemetry Collector (contrib distribution) that
receives OTLP and exposes a Prometheus endpoint, and scrape the collector.

```yaml
# group_vars/rustfs
rustfs_extra_env:
  RUSTFS_OBS_ENDPOINT: "http://otel-collector.example.com:4318"
  # Metrics only; logs stay in journald.
  RUSTFS_OBS_TRACES_EXPORT_ENABLED: "false"
  RUSTFS_OBS_LOGS_EXPORT_ENABLED: "false"
```

```yaml
# OpenTelemetry Collector configuration
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318
exporters:
  prometheus:
    endpoint: 0.0.0.0:8889
service:
  pipelines:
    metrics:
      receivers: [otlp]
      exporters: [prometheus]
```

Prometheus then scrapes `otel-collector.example.com:8889`. The journal keeps
the logs either way: the role always mirrors them to stdout
(`RUSTFS_OBS_LOG_STDOUT_ENABLED`). Changing `rustfs_extra_env` is a rolling
restart.

---

## Server-side encryption with OpenBao Transit

RustFS manages SSE-KMS keys through an external KMS; its `vault-transit`
backend works with OpenBao (same API), for example a cluster deployed with
`ansible-role-openbao`. On OpenBao, create a Transit mount, a KV v2 mount
for RustFS's key metadata, a policy and an AppRole (upstream walkthrough:
`docs/security-compliance/encryption/openbao.md` of the RustFS docs):

```bash
bao secrets enable -path=rustfs-transit transit
bao secrets enable -path=rustfs-meta -version=2 kv
bao policy write rustfs-kms rustfs-kms.hcl   # Transit keys, encrypt, decrypt, rewrap; KV data and metadata
bao auth enable approle
bao write auth/approle/role/rustfs token_policies=rustfs-kms token_ttl=1h token_max_ttl=24h
bao read -field=role_id auth/approle/role/rustfs/role-id
bao write -f -field=secret_id auth/approle/role/rustfs/secret-id
```

Then configure RustFS through the two extra env dicts (the role validates
the keys and keeps the AppRole credentials in `secrets.env`):

```yaml
# group_vars/rustfs
rustfs_extra_env:
  RUSTFS_KMS_ENABLE: "true"
  RUSTFS_KMS_BACKEND: "vault-transit"
  RUSTFS_KMS_VAULT_ADDRESS: "https://openbao.example.com:8200"
  RUSTFS_KMS_VAULT_MOUNT_PATH: "rustfs-transit"
  RUSTFS_KMS_VAULT_TRANSIT_METADATA_KV_MOUNT: "rustfs-meta"
  RUSTFS_KMS_VAULT_TRANSIT_METADATA_PREFIX: "rustfs/kms/keys"
  RUSTFS_KMS_VAULT_CA_CERT: "/etc/rustfs/openbao-ca.pem"
rustfs_extra_secret_env:
  RUSTFS_KMS_VAULT_APPROLE_ROLE_ID: "{{ vault_rustfs_kms_role_id }}"
  RUSTFS_KMS_VAULT_APPROLE_SECRET_ID: "{{ vault_rustfs_kms_secret_id }}"
```

RustFS renews the AppRole token in the background. Copy the OpenBao CA to
`/etc/rustfs/openbao-ca.pem` (`root:root 0644`) in a pre-task; the config
directory is readable by the service group. RustFS requires HTTPS to the
KMS. Create the first key from RustFS (console, "SSE Settings"), not
directly in OpenBao, then set `RUSTFS_KMS_DEFAULT_KEY_ID` in
`rustfs_extra_env` and run the play (a rolling restart). Losing the Transit
key makes the encrypted objects unreadable: back up OpenBao independently
of RustFS.

---

## Mirrors and egress

Each target downloads its release zip itself, once per version. By default
from GitHub: `https://github.com/rustfs/rustfs/releases/download/<version>/<asset>`,
which redirects to `release-assets.githubusercontent.com`, so both hosts
need HTTPS egress. The asset name is
`rustfs-linux-<x86_64|aarch64>-<musl|gnu>-v<version>.zip` (the tag has no
`v`, the file name has one).

For an internal mirror (Nexus raw repository, Artifactory, a web server),
keep the `<base>/<version>/<asset>` layout and set
`rustfs_download_base_url`. The digest comes from, in this order:
`rustfs_checksum`, the digest pinned in the role for its default version,
or `<base>/<version>/SHA256SUMS` (the mirror must then serve that file too).
`dl.rustfs.com` cannot be used as the base: it has no version directories
and no `SHA256SUMS`. Upstream publishes no signatures, so take digests from
the GitHub release, not from the mirror. Package dependencies (`unzip`,
`ca-certificates`, `python3-cryptography`) come from the OS repositories.

---

## Post-role workflow

After the role completes successfully:

1. **Check the cluster:**
   ```bash
   curl -s --cacert ca.crt https://rustfs1.example.com:9000/health/ready | jq .
   curl -s -o /dev/null -w '%{http_code}\n' --cacert ca.crt \
     https://rustfs1.example.com:9000/minio/health/cluster
   ```
   Every node answers `"ready": true`, and the cluster endpoint 200.

2. **Create an admin IAM user and stop using the root keys.** The root
   credentials bypass IAM policies; keep them in Ansible Vault for the role
   and for emergencies only:
   ```bash
   rc alias set prod https://s3.example.com <root access key> <root secret key>
   rc admin user add prod admin <admin secret key>
   rc admin policy attach prod consoleAdmin --user admin
   # Replace the alias: from now on rc works as the admin user.
   rc alias set prod https://s3.example.com admin <admin secret key>
   ```
   Then create one user or service account per application with a scoped
   policy (`rc admin policy create`).

3. **Create buckets with Terraform** ([Terraform](#terraform)), with
   versioning and lifecycle rules where the consumer needs them.

4. **Set up monitoring:** a load balancer or blackbox probe on
   `/health/ready` per node and `/minio/health/cluster`, metrics through the
   OpenTelemetry Collector, and the RustFS journal in Loki.

5. **Test a node failure** before going live: stop RustFS on one node, check
   that S3 reads and writes still work through the others, start it again
   with `systemctl start --no-block rustfs`, and watch it become ready and
   re-admitted ([Restarting a node by
   hand](TROUBLESHOOTING.md#restarting-a-node-by-hand)).
