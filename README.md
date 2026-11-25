# Ansible Role - RustFS

[![CI](https://github.com/devopsgroupeu/ansible-role-rustfs/actions/workflows/ci.yml/badge.svg)](https://github.com/devopsgroupeu/ansible-role-rustfs/actions/workflows/ci.yml)
[![Ansible Galaxy](https://img.shields.io/badge/Ansible%20Galaxy-devopsgroupeu.rustfs-blue?logo=ansible)](https://galaxy.ansible.com/ui/standalone/roles/devopsgroupeu/rustfs/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
![GitHub Forks](https://img.shields.io/github/forks/devopsgroupeu/ansible-role-rustfs)
![GitHub Stars](https://img.shields.io/github/stars/devopsgroupeu/ansible-role-rustfs)
![GitHub Issues](https://img.shields.io/github/issues/devopsgroupeu/ansible-role-rustfs)

[![LinkedIn](https://img.shields.io/badge/linkedin-%230077B5.svg?style=for-the-badge&logo=linkedin&logoColor=white)](https://www.linkedin.com/company/devopsgroup8/)
![RustFS](https://img.shields.io/badge/RustFS-0196D0?logo=rustfs&logoColor=fff&style=for-the-badge)

Production-ready Ansible role for installing and configuring **RustFS**
S3-compatible object storage (Apache-2.0) as a single node or a distributed
erasure-coded cluster with TLS, systemd hardening and health-gated rolling
restarts. It installs checksum-verified, versioned release binaries, refuses
default credentials, unmounted drives and accidental layout changes, and
restarts a cluster one node at a time without `serial`.

---

## Requirements

- **Ansible:** 2.19 or later (`ansible-core >= 2.19, < 2.22`)
- **Collections:** `community.crypto >= 3.2.2`
  Install via: `ansible-galaxy collection install -r requirements.yml`
- **Target OS:** Ubuntu 24.04 (noble), Debian 12/13 (bookworm/trixie), RHEL/Rocky/Alma 9; `x86_64` or `aarch64`; systemd
- **RustFS version:** 1.0.6 (default; override via `rustfs_version`)
- **On the targets:** Python 3 for Ansible. The role installs `unzip`,
  `ca-certificates` and `python3-cryptography` on the first install; render
  mode (`rustfs_config_only`) with BYO TLS needs `python3-cryptography`
  already present.
- **Egress:** HTTPS from every target to `github.com` and
  `release-assets.githubusercontent.com`, or a mirror
  (`rustfs_download_base_url`, see
  [docs/INTEGRATION.md](docs/INTEGRATION.md#mirrors-and-egress))
- **Drives:** every data dir is a mounted drive (XFS, one per physical
  disk, in `/etc/fstab` with `nofail`, on a `root:root` mount point); the
  role checks but never formats or mounts
- **Cluster:** node names resolve on every node, through DNS or
  `/etc/hosts` (the default `musl` build does not use NSS modules such as
  `nss-myhostname`, `nss-resolve` or `sssd`; use `rustfs_libc: "gnu"` where
  names resolve only there), clocks are synchronised, TCP 9000 is open
  between the nodes
- **Docker (Molecule):** required for running tests locally
- **`become: true` at the play level** - the role does not set `become` per-task

---

## Quick start

### Install

```bash
ansible-galaxy collection install -r requirements.yml
ansible-galaxy role install devopsgroupeu.rustfs
```

Or pin a version from Git:

```yaml
# requirements.yml
roles:
  - name: devopsgroupeu.rustfs
    src: https://github.com/devopsgroupeu/ansible-role-rustfs.git
    version: "vX.Y.Z"   # latest release tag, see GitHub Releases
    scm: git
```

### Single node, single drive (dev/test - generated TLS)

```yaml
- name: Deploy RustFS
  hosts: rustfs_dev
  become: true
  roles:
    - role: devopsgroupeu.rustfs
      vars:
        rustfs_volumes:
          - "/data/rustfs0"
        rustfs_tls_generate_certs: true            # dev/test only
        rustfs_require_mounted_drives: false       # dev/test only: a plain directory
        rustfs_access_key: "{{ vault_rustfs_access_key }}"   # from Ansible Vault
        rustfs_secret_key: "{{ vault_rustfs_secret_key }}"   # from Ansible Vault
```

A single plain path is the single-drive layout: it can never gain a pool.

### Single node, multiple drives (BYO TLS)

```yaml
- name: Deploy RustFS
  hosts: rustfs_single
  become: true
  roles:
    - role: devopsgroupeu.rustfs
      vars:
        rustfs_volumes:
          - "/data/rustfs{0...3}"                  # four mounted drives
        rustfs_node_address: "{{ inventory_hostname }}"   # a SAN of the BYO certificate
        rustfs_access_key: "{{ vault_rustfs_access_key }}"
        rustfs_secret_key: "{{ vault_rustfs_secret_key }}"
        rustfs_iam_master_key: "{{ vault_rustfs_iam_master_key }}"
```

`rustfs_cert.pem`, `rustfs_key.pem` and `ca.crt` must be in `/etc/rustfs/tls`
before the run ([BYO certificates](docs/INTEGRATION.md#byo-certificates)).

### Four-node distributed cluster (BYO TLS)

```yaml
# group_vars/rustfs.yml - identical for every node
rustfs_volumes:
  - "https://rustfs{1...4}.example.com:9000/data/rustfs{0...3}"
rustfs_access_key: "{{ vault_rustfs_access_key }}"
rustfs_secret_key: "{{ vault_rustfs_secret_key }}"
rustfs_rpc_secret: "{{ vault_rustfs_rpc_secret }}"            # required in distributed mode
rustfs_iam_master_key: "{{ vault_rustfs_iam_master_key }}"    # required in distributed mode
```

```yaml
- name: Deploy RustFS cluster
  hosts: rustfs            # exactly the four nodes, named rustfs1.example.com ... rustfs4.example.com
  become: true
  roles:
    - role: devopsgroupeu.rustfs
```

The inventory names must be the host names in `rustfs_volumes`, and every
node certificate needs its name as a DNS SAN. Run the first bootstrap
against all nodes in one play (no `--limit`, no `serial`). Upstream
documents a minimum of four nodes for a distributed deployment; the role
does not assert it, because RustFS validates smaller layouts itself.

See `examples/` for the complete playbooks and inventory.

Check mode (`--check --diff`) is supported on hosts the role has converged
before; it reports drift and pending restarts and changes nothing. A first
install cannot run in check mode (the service user and the binary do not
exist yet).

---

## Role variables

All 44 variables are documented in full in **[`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)**.
Every variable is prefixed `rustfs_`, declared in `defaults/main.yml`, and validated
by `meta/argument_specs.yml` (1:1 mapping).

Key variables to be aware of:

| Variable | Default | Notes |
|---|---|---|
| `rustfs_version` | `"1.0.6"` | Pinned. A bump installs the new binary next to the old one and rolls the cluster node by node |
| `rustfs_volumes` | `[]` | **Required.** Upstream volume expressions, one per pool (`{0...3}`, three dots). Immutable once bootstrapped |
| `rustfs_access_key`, `rustfs_secret_key` | `""` | **Required**, from Ansible Vault. `rustfsadmin` is refused |
| `rustfs_rpc_secret` | `""` | Required in distributed mode. A change restarts the cluster together |
| `rustfs_iam_master_key` | `""` | Required in distributed mode, recommended everywhere. Encrypts IAM data at rest |
| `rustfs_tls_enabled` | `true` | **TLS on by default** with BYO certificates in `rustfs_tls_dir`. Decide before the first bootstrap |
| `rustfs_tls_generate_certs` | `false` | `true` = private CA and node certificates (dev/test only) |
| `rustfs_require_mounted_drives` | `true` | Every data dir must be a mount point when the role runs; the unit waits for the mounts but a lost drive is one offline drive, not a node down |
| `rustfs_allow_volumes_change` | `false` | One-run override for appending or removing a pool |
| `rustfs_console_address` | `":9001"` | All interfaces: bind it to a management address or firewall it |
| `rustfs_extra_env`, `rustfs_extra_secret_env` | `{}` | Any other `RUSTFS_*` setting (KMS, OIDC, OTLP, notifications) |
| `rustfs_rolling_restart` | `true` | `false` = restart all changed nodes together |
| `rustfs_allow_downgrade` | `false` | Set for a rollback to the previous release |
| `rustfs_config_only` | `false` | `true` = render the files only (no install, no service) |

---

## Security notes

### Default credentials

RustFS falls back to the public credentials `rustfsadmin` / `rustfsadmin`.
**The role refuses to render them**, and refuses empty, short or malformed
keys, before anything is touched. Generate the access key as 20 random
uppercase letters and digits and the secrets with `openssl rand -base64 30`,
and keep them in Ansible Vault.

### Secret storage

Credentials, the RPC secret, the IAM master key and
`rustfs_extra_secret_env` go to `/etc/rustfs/secrets.env` (`root:root 0600`)
only. **The unit file and the env file (`/etc/default/rustfs`, readable by
the service group, shown in `--diff`) never contain a secret.** Every task
that touches a secret runs with `no_log: true`, and no validation message
echoes a secret value.

### IAM master key

**Without `RUSTFS_IAM_MASTER_KEY` RustFS stores IAM users, policies and
service-account secrets in plaintext on the drives**, and refuses MFA
enrollment. `rustfs_iam_master_key` is required in distributed mode and
recommended for single nodes. Losing the key makes the encrypted IAM data
unreadable: store it with the other secrets and back it up.

### TLS and private CAs

TLS is **on by default** and covers S3, console and internode traffic with
one certificate per node. RustFS trusts `ca.crt` (and `public.crt`) in the
TLS directory; `rustfs_tls_trust_system_ca: true` adds the OS store on top.
With a private CA, `ca.crt` is the trust anchor and is required, and the
role's health probes use it whenever it exists. The key is
`root:rustfs 0640`. The role checks BYO material before it can break a
node: validity, serverAuth in an extended key usage, a SAN for
`rustfs_node_address`, and that the key belongs to the certificate. Server
mTLS (`RUSTFS_SERVER_MTLS_ENABLE`) is not supported: the role's health
probes have no client certificate.

### Generated certificates (CA key on every node)

**`rustfs_tls_generate_certs: true` copies the private CA key to every
node** (`ca.key`, `root:root 0600`), so anyone with root on one node can
issue certificates the others trust. Use it for dev/test only; production
uses BYO certificates from your PKI.

### Console exposure

The console listens on `:9001` on **all interfaces** by default and accepts
the root credentials. Bind it to a management address
(`rustfs_console_address: "10.0.0.11:9001"`), firewall it, or disable it
(`rustfs_console_enabled: false`).

### Binary integrity

**Upstream publishes no signatures**, only `SHA256SUMS`. The role verifies
the release zip against a SHA-256 pinned in `vars/main.yml` for its default
version, against `rustfs_checksum`, or against `SHA256SUMS` from the same
release (HTTPS only: a plain `http://` mirror needs a pinned or given
digest), and the extracted binary must report `rustfs_version`, run as the
unprivileged service user, before it is installed. The role records the
SHA-256 of every binary it installed (`rustfs-<version>-<libc>.sha256`) and
downloads and verifies again a versioned binary that does not match it. A
pinned digest fails closed if an asset is replaced upstream later; the
other two paths trust the download source.

### Root credentials are not application credentials

The root keys bypass IAM policies. Create IAM users or service accounts
with scoped policies for every application, and keep the root keys for the
role and for emergencies
([Post-role workflow](docs/INTEGRATION.md#post-role-workflow)).

### Become

The role relies on `become: true` at the play level: the service tasks, the
daemon-reload handler and the reads of `/proc` need root.

### Reading the process environment

To decide restarts, and to guard layout, cluster-wide and IAM master key
changes, the role reads `/proc/<MainPID>/environ` of the running RustFS
process and the deployed `secrets.env` as root. They hold the secrets; they
are read in `no_log` tasks and never stored as facts (role variables
template them where they are compared). The decision facts, the guard
messages and the "RustFS restarts" message contain key names only.

---

## Operations

### How restarts work

There is no restart handler. Every run compares each node's running binary,
environment and served certificate with the desired state and restarts only
what differs: **one node at a time** for ordinary changes (every peer ready
and every drive online before a node goes down, every drive online again
after it), **all changed nodes together** for an RPC secret or a volume
change, or when `rustfs_rolling_restart: false`. A run that died half way,
or a `--tags config` run, is completed by the next run with exactly one
restart. Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#restart-decision-and-rolling-restart).

- Run the role against the whole cluster in one play with the default
  linear strategy (`strategy: free` or `host_pinned` is refused where the
  role compares hosts). **Do not set `serial`** (refused): the role
  serialises restarts itself, over the changed nodes of the whole play.
- `--limit <node>` is fine for day-2 work on a healthy cluster, but cannot
  bootstrap a cluster, and cannot change `rustfs_volumes`, the RPC secret,
  the root credentials or the IAM master key (all refused: they must change
  on every node in the same run). Add or replace nodes with a full-cluster
  run.
- With a drive offline, a rolling restart is refused: replace the drive
  first ([TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md#a-drive-is-offline)),
  or use `rustfs_rolling_restart: false` in a maintenance window.
- Stage tags `install`, `config`, `tls` and `service` select stages when the
  role is applied statically (`roles:` or `import_role`); the guards are
  tagged `always` and run with any selection. A start or restart loads the
  files on disk, so `--tags service` refuses when a changed variable has
  not been rendered yet: include `config` (and `install` for a version).
- A failed rollout stops the play on every host; re-running it resumes.

### Upgrade

Read the release notes of every version you cross, then set
`rustfs_version` (and update `rustfs_checksum` if you pin digests yourself).
The run downloads and verifies the new binary on every node, then restarts
the nodes one at a time, switching each node's `rustfs` symlink right
before its restart: a rollout that stops at the first node leaves the others
on the old binary, even if they restart or reboot before you roll back.
Upstream rules: finish the upgrade on every node before any pool change or
decommission, and never enable a "version floor" feature gate (see
[CONFIGURATION.md](docs/CONFIGURATION.md#notes)) while versions are mixed.

### Rollback

Set `rustfs_version` back to the previous release and
`rustfs_allow_downgrade: true` for that run. The previous binary is still
installed, so nothing is downloaded and the nodes roll one at a time.
Upstream documents only an immediate rollback to the previous release.

### Rotating secrets

- **Root credentials:** change `rustfs_access_key` / `rustfs_secret_key`
  and run the play: a rolling restart. It is safe in a cluster because the
  RPC secret is explicit. Update the clients that use the root keys; STS
  sessions signed with the old secret key stop working.
- **RPC secret:** change `rustfs_rpc_secret` and run the play. Old and new
  secret cannot talk to each other, so the role restarts the cluster
  together (a short outage).
- **IAM master key:** RustFS encrypts IAM data with the current key,
  decrypts with it and with `RUSTFS_IAM_MASTER_KEY_OLD_KEYS` (a
  comma-separated list), and rewrites every entry it read with an old key
  using the current one. A node restarted with the new key therefore
  rewrites IAM data that nodes still running with only the old key cannot
  read (`NoSuchUser`). Rotate a cluster in **two runs**, each a rolling
  restart:

  ```yaml
  # Run 1: every node learns to decrypt the new key, still encrypts with the old one.
  rustfs_iam_master_key: "{{ vault_rustfs_iam_master_key_1 }}"
  rustfs_extra_secret_env:
    RUSTFS_IAM_MASTER_KEY_OLD_KEYS: "{{ vault_rustfs_iam_master_key_2 }}"
  ```

  ```yaml
  # Run 2: swap them; every node can still read entries of the old key.
  rustfs_iam_master_key: "{{ vault_rustfs_iam_master_key_2 }}"
  rustfs_extra_secret_env:
    RUSTFS_IAM_MASTER_KEY_OLD_KEYS: "{{ vault_rustfs_iam_master_key_1 }}"
  ```

  A single node needs only run 2. Preflight refuses a change that drops the
  key a node runs with from the old keys (its IAM data would become
  unreadable) and, in a cluster, a new current key that a running node
  cannot decrypt yet (run 2 before run 1 completed on every node). Keep the
  old key listed: RustFS rewrites entries as it reads them, and IAM is read
  in full at every start.

### Pool expansion and decommission

A pool layout is immutable. Capacity grows by **appending** a pool
expression to `rustfs_volumes` on every node (the new nodes in the same
inventory group and play), with `rustfs_allow_volumes_change: true` for that
run; the role restarts the changed nodes together. Existing data moves only
with `rc admin rebalance start`. Removing a pool: decommission it with
`rc admin decommission start`, wait for `complete`, then remove its
expression with the same override. A single-drive deployment cannot be
expanded. Follow the upstream runbooks for both procedures; the role only
renders and restarts.

### Drives and reboots

Mount every drive through `/etc/fstab` by UUID with `nofail`, on a mount
point that stays `root:root` while unmounted. With
`rustfs_require_mounted_drives: true` (the default) the role runs only when
every data dir is mounted, and the unit is ordered after the mounts without
depending on them. After a reboot with a failed mount, or when a disk drops
out at runtime, the node keeps serving on its other drives (one offline
drive, not a node down), and RustFS cannot write to the root-owned directory
below the mount point. Boot does not wait for RustFS either.

To replace a failed disk: mount an empty, identically formatted one at the
same path, restart RustFS on that node (so it sees the new mount), run the
play for that node (it sets the owner of the new filesystem; `--limit` is
fine), and wait until no node lists the drive in `/health/ready` any more
(RustFS formats and heals it). Until then rolling restarts are refused. Step
by step: [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md#a-drive-is-offline).

### Service user and group

`rustfs_user` and `rustfs_group` are fixed after the first bootstrap:
ownership of the data dirs is set on the mount points only, never
recursively, so a rename would leave the object data owned by the old user.

---

## Tests (Molecule)

```bash
# Install test dependencies
pip install -r requirements.txt
ansible-galaxy collection install -r requirements.yml

# Offline (no RustFS binary): render the files in many variants; variable, layout and TLS guard refusals
molecule test -s render

# Single node, four tmpfs drives, generated TLS: install, start, S3 round trip,
# behaviour plays (stage tags, an unmounted and a replaced drive, certificate
# reloads, IAM master key change, symlinked binary directory, proxies)
molecule test -s default

# Upgrade, downgrade refusal and rollback between two releases
molecule test -s upgrade

# Four-node cluster with tmpfs drives: parallel bootstrap, rolling and together
# restarts, dead peer, offline drive, free strategy, two-run IAM key rotation
molecule test -s distributed

# Another distribution (debian12 is the default)
MOLECULE_DISTRO=ubuntu2404 molecule test -s default
```

The CI pipeline (`ci.yml`) runs on pushes and pull requests to `main` and
`develop`. The `lint` job runs `yamllint`,
`ansible-lint --profile production` on the role and on the Molecule and
example playbooks, and the variable count and ASCII checks of
[CONTRIBUTING.md](CONTRIBUTING.md). The `molecule` job runs `render` and
`default` on `debian12`, `debian13` and `ubuntu2404`, and `upgrade` on
`debian12`. On `default`/`debian12` it keeps
the container, fails when a test secret appears in the Molecule log, and runs
a check-mode converge (`--check --diff`) of the converged host that must
report `changed=0` and `failed=0` and print no secret. The
`molecule-distributed` job runs `distributed` on `debian12`. A single
`ci-success` job aggregates the results.

EL 9 is declared in `meta/main.yml` but not yet validated. On the
`rockylinux9` image the role converges, stays idempotent and passes check
mode and every `default` verify assert except the S3 round trip: the image's
curl 7.76.1 cannot sign SigV4 requests that RustFS accepts
(`SignatureDoesNotMatch`). Reproduce with
`MOLECULE_DISTRO=rockylinux9 molecule test -s default`.

---

## File layout

```
ansible-role-rustfs/
|-- defaults/main.yml              # 44 public variables
|-- vars/main.yml                  # derived values, env dicts, pinned digests (internal)
|-- meta/main.yml                  # Galaxy metadata
|-- meta/argument_specs.yml        # 1:1 with defaults (44 options)
|-- handlers/main.yml              # systemd daemon-reload only (no restart handler)
|-- tasks/
|   |-- main.yml                   # orchestrator
|   |-- validate.yml               # variable and play-shape guards (tag always)
|   |-- preflight.yml              # read-only host and process probes and guards (tag always)
|   |-- install.yml                # user, deps, checksum-verified versioned binary and its digest file
|   |-- config.yml                 # directories, secrets.env, unit, env file
|   |-- tls.yml                    # dispatch BYO or generated TLS
|   |-- tls_byo.yml                # BYO owner/mode, validity, EKU, SAN and key checks
|   |-- tls_generate.yml           # dev/test CA and node certificates (community.crypto)
|   |-- service.yml                # restart decision, symlink, start, rollout, quorum gate
|   |-- restart_node.yml           # one node: peer and drive checks, symlink, restart, wait, re-admission
|   `-- wait_ready.yml             # one node: new main PID, then /health/ready
|-- templates/
|   |-- rustfs.env.j2
|   |-- rustfs.secrets.env.j2
|   `-- rustfs.service.j2
|-- molecule/{render,default,upgrade,distributed}/
|-- molecule/shared/tasks/         # helpers shared by the scenarios
|-- examples/{single_node.yml,distributed_cluster.yml}
|   `-- inventory/rustfs_cluster.yml
|-- docs/{ARCHITECTURE.md,CONFIGURATION.md,INTEGRATION.md,TROUBLESHOOTING.md}
`-- .github/workflows/{ci.yml,galaxy.yml,pre-commit.yml,release.yml,release-drafter.yml}
```

---

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) to get started.

## Code of Conduct

Read our [Code of Conduct](CODE_OF_CONDUCT.md).

## Changelog

See the [GitHub Releases](https://github.com/devopsgroupeu/ansible-role-rustfs/releases) page for release history.

## License

```
Copyright 2026 DevOpsGroup

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

---

> For more information or support, please refer to the official documentation or contact us at info@devopsgroup.sk
