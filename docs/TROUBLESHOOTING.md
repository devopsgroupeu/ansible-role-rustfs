# Troubleshooting

Failure modes of the `devopsgroupeu.rustfs` role and of RustFS itself, with
every fail-closed message the role can emit.

---

## Table of Contents

- [How to read this page](#how-to-read-this-page)
- [Argument validation](#argument-validation)
- [Variable guards (validate.yml)](#variable-guards-validateyml)
- [Host guards (preflight.yml)](#host-guards-preflightyml)
- [Install guard (install.yml)](#install-guard-installyml)
- [TLS guards (tls_byo.yml and service.yml)](#tls-guards-tls_byoyml-and-serviceyml)
- [Service guard (service.yml)](#service-guard-serviceyml)
- [Rollout failures (wait_ready.yml and restart_node.yml)](#rollout-failures-wait_readyyml-and-restart_nodeyml)
- [Download checksum mismatch](#download-checksum-mismatch)
- [Readiness timeout on the first bootstrap](#readiness-timeout-on-the-first-bootstrap)
- [Distinct physical disks](#distinct-physical-disks)
- [Unsupported filesystem](#unsupported-filesystem)
- [Unit exits with 226/NAMESPACE](#unit-exits-with-226namespace)
- [A drive is offline](#a-drive-is-offline)
- [PoolTopologyMismatch](#pooltopologymismatch)
- [x509 and TLS errors between peers](#x509-and-tls-errors-between-peers)
- [503 with Retry-After during a rollout](#503-with-retry-after-during-a-rollout)
- [A rollout is refused because a peer is down](#a-rollout-is-refused-because-a-peer-is-down)
- [Hosts stay failed after a rescued rollout](#hosts-stay-failed-after-a-rescued-rollout)
- [Restarting a node by hand](#restarting-a-node-by-hand)
- [Useful commands](#useful-commands)

---

## How to read this page

Each `###` heading below is the name of the task the play stops at, exactly
as it appears in the Ansible output (`TASK [devopsgroupeu.rustfs : <name>]`).
Names that contain `{{ __rustfs_node }}` or `{{ __rustfs_wait_node }}` show
the inventory name of the node in the output. The block under the heading is
the message, with `<value>` where the role inserts the actual value.

- The guards in `validate.yml` and `preflight.yml` only read. A host that
  fails one is left untouched, and they are tagged `always`, so no `--tags`
  selection skips them.
- No message shows a secret value: credential messages name the variable
  only.
- In distributed mode most guards run on every host, so every host reports
  the same failure.

---

## Argument validation

Role argument validation (`meta/argument_specs.yml`) runs before any role
task.

### Validating arguments against arg spec 'main' - Install and configure RustFS S3-compatible object storage, single node or distributed

**Symptom:** the play stops before the first role task with, for example:

```
Validation of arguments failed:
value of rustfs_libc must be one of: musl, gnu, got: glibc
```

**Cause:** a variable has a value outside its `choices` (`rustfs_libc`,
`rustfs_unsupported_fs_policy`, `rustfs_log_level`, `rustfs_service_state`)
or a type that cannot be converted.

**Fix:** use one of the listed values; see
[CONFIGURATION.md](CONFIGURATION.md).

### `object of type 'dict' has no attribute 'architecture'`

**Symptom:** argument validation fails with this message.

**Cause:** the play has `gather_facts: false` and no earlier play gathered
facts for the host. The default of `rustfs_arch` reads
`ansible_facts['architecture']`.

**Fix:** gather facts (`gather_facts: true`, the default) in the play that
applies the role, or in an earlier play of the same run.

---

## Variable guards (validate.yml)

These run first, in every mode (render mode too), before the host is
touched.

### Validate rustfs_version

**Symptom:** the play stops here with:

```
rustfs_version '<value>' is not a bare SemVer version. Use the upstream tag
format without a "v" prefix, for example "1.0.6".
```

**Cause:** a `v` prefix (`v1.0.6`), a partial version (`1.0`) or a word
(`latest`).

**Fix:** use the bare upstream tag, for example `rustfs_version: "1.0.6"`.
For a version without a pinned digest the mirror must also serve
`SHA256SUMS`, or set `rustfs_checksum`.

### Validate rustfs_arch

**Symptom:** the play stops here with:

```
Unsupported architecture '<value>' (ansible_facts['architecture']; resolved
rustfs_arch '<value>'). RustFS ships x86_64 and aarch64 builds only. Set
rustfs_arch to "x86_64" or "aarch64" only if the facts name one of them
differently.
```

**Cause:** the host is neither x86_64 nor aarch64.

**Fix:** run RustFS on an x86_64 or aarch64 host. Set `rustfs_arch` only when
the facts report one of these two under another name.

### Validate the choice variables

**Symptom:** the play stops here with:

```
A choice variable has a value outside its choices: rustfs_libc '<value>'
(musl, gnu), rustfs_unsupported_fs_policy '<value>' (fail, warn),
rustfs_log_level '<value>' (trace, debug, info, warn, error),
rustfs_service_state '<value>' (started, stopped).
```

**Cause:** a typo such as `rustfs_service_state: restarted`, in a run that
skips role argument validation (`include_role` with
`rolespec_validate: false`, or `tasks_from`). Normally argument validation
refuses the value first ("must be one of").

**Fix:** use one of the listed values.

### Validate rustfs_checksum

**Symptom:** the play stops here with:

```
rustfs_checksum '<value>' is not a SHA-256 digest. Set the 64 lowercase hex
characters of the release zip digest (no "sha256:" prefix), or leave it
empty to use the pinned digest of the default version or the SHA256SUMS file
next to the asset.
```

**Cause:** a prefix, upper-case hex, a SHA-512 digest or a truncated value.

**Fix:** copy the digest of the exact asset from the release `SHA256SUMS`:
`grep rustfs-linux-x86_64-musl-v1.0.6.zip SHA256SUMS | cut -d' ' -f1`.

### Validate rustfs_download_base_url

**Symptom:** the play stops here with:

```
rustfs_download_base_url '<value>' is not an https:// URL, and no digest
covers rustfs_version <value> (<value>-<value>): the zip and its SHA256SUMS
would both come unauthenticated from that origin. Serve the mirror over
HTTPS, or set rustfs_checksum to the digest from the upstream release.
```

**Cause:** a plain `http://` mirror for a version without a pinned digest
and without `rustfs_checksum`: whoever sits on the network path could
replace both the zip and the digest list.

**Fix:** serve the mirror over HTTPS, or set `rustfs_checksum` to the digest
from the upstream GitHub release `SHA256SUMS`
([INTEGRATION.md](INTEGRATION.md#mirrors-and-egress)).

### Validate rustfs_address

**Symptom:** the play stops here with:

```
rustfs_address '<value>' is not "[host]:port" with a port from 1 to 65535.
Examples: ":9000" (all interfaces), "10.0.0.11:9000", "[fd00::11]:9000".
```

**Cause:** no port (`"0.0.0.0"`), no colon (`"9000"`) or a port out of range.

**Fix:** use `"[host]:port"`; IPv6 hosts go in brackets.

### Validate rustfs_console_address

**Symptom:** the play stops here with:

```
rustfs_console_address '<value>' is not "[host]:port" with a port from 1 to
65535, or the console is enabled and its port equals the S3 port of
rustfs_address '<value>'. Use another port for the console (default ":9001")
or set rustfs_console_enabled: false.
```

**Cause:** the same format errors as above, or the console and S3 listeners
share a port.

**Fix:** give the console its own port, or disable it.

### Validate rustfs_volumes is a list of volume expressions

**Symptom:** the play stops here with:

```
rustfs_volumes <value> must be a non-empty list of non-empty strings without
whitespace, one upstream volume expression per server pool, for example
["/data/rustfs{0...3}"] or
["https://rustfs{1...4}.example.com:9000/data/rustfs{0...3}"].
```

**Cause:** `rustfs_volumes` is not set (the default is `[]`), is a string
instead of a list, holds an empty item, or holds two pools in one item
separated by a space.

**Fix:** one list item per pool, set once for the cluster in `group_vars`.

### Validate rustfs_volumes uses three-dot ranges

**Symptom:** the play stops here with:

```
rustfs_volumes <value> contains a two-dot range such as {0..3}. That is
shell brace syntax; RustFS expands only three-dot ranges: write {0...3}.
```

**Cause:** a range copied from a shell or Docker Compose example.

**Fix:** write `{0...3}`.

### Validate rustfs_volumes does not mix paths and URLs

**Symptom:** the play stops here with:

```
rustfs_volumes <value> must be all local paths (single node, starting with
"/") or all URLs (cluster, starting with "https://" or "http://"), not a
mix.
```

**Cause:** a local path next to URL items, or an item without a scheme.

**Fix:** a single node uses local paths only; a cluster uses URLs only.

### Validate rustfs_volumes uses pool expressions

**Symptom:** the play stops here with:

```
rustfs_volumes <value> has more than one item or URL items, so every item
must be a pool expression with an ellipsis, for example
"https://rustfs{1...4}:9000/data/rustfs{0...3}". Only a single local item
may be a plain path ("/data/rustfs0", one drive).
```

**Cause:** several plain paths (`["/data/a", "/data/b"]`, the upstream
legacy style), or a URL item without a range.

**Fix:** write each pool as one expression with a range
(`/data/rustfs{0...3}`). Only a single node with a single drive uses one
plain path.

### Validate the ellipsis ranges of rustfs_volumes

**Symptom:** the play stops here with:

```
rustfs_volumes items <value> have an invalid range. The host part and the
path part may each hold at most one decimal range {N...M} with N <= M
({01...12} zero-pads); hex ranges and other braces are not supported by this
role.
```

**Cause:** a reversed range (`{3...0}`), a hex range (`{a...f}`), two ranges
in the host or in the path part, or a stray brace.

**Fix:** one ascending decimal range per part, for example
`https://rustfs{1...4}:9000/data/rustfs{0...3}`.

### Validate the scheme and port of the rustfs_volumes URLs

**Symptom:** the play stops here with:

```
rustfs_volumes <value> must use the scheme "<value>://" and, when a URL
names a port, the port <value> of rustfs_address '<value>' (ports found:
<value>). TLS on (rustfs_tls_enabled) means https:// volumes, TLS off means
http:// volumes. Nodes talk to each other on the S3 port; there is no
separate cluster port.
```

**Cause:** `http://` volumes with TLS on (the default) or `https://` volumes
with TLS off, or a URL port that differs from the listener port.

**Fix:** match the scheme to `rustfs_tls_enabled` and the port to
`rustfs_address`. Changing the scheme of a running cluster changes the
deployed layout; decide on TLS before the first bootstrap.

### Validate the role paths

**Symptom:** the play stops here with:

```
Refused paths: <value>; rustfs_data_dirs <value> must be a non-empty list.
Every entry of rustfs_data_dirs and rustfs_systemd_read_write_paths, and
rustfs_home, rustfs_config_dir and rustfs_tls_dir, must be absolute, must
not be "/" and must not be at or under /tmp or /var/tmp (hidden by
PrivateTmp) or /home, /root or /run/user (hidden by ProtectHome).
```

**Cause:** a relative path, `/`, or a path the unit's sandbox hides from
RustFS (it would write into a private, empty view of that directory).

**Fix:** move the path, for example drives under `/data`, extra paths under
`/var/lib`.

### Validate rustfs_data_dirs are unique and not nested

**Symptom:** the play stops here with:

```
rustfs_data_dirs <value> has duplicate or nested entries: <value>. Every
drive needs its own directory, and RustFS refuses a drive inside another
drive.
```

**Cause:** two entries name the same directory (also after removing a
trailing `/`), or one entry lies inside another.

**Fix:** one separate mount point per drive, for example `/data/rustfs0` to
`/data/rustfs3`, never `/data` plus `/data/rustfs0`.

### Validate rustfs_access_key

**Symptom:** the play stops here with:

```
rustfs_access_key is empty, is the public upstream default "rustfsadmin", or
is not 3 to 128 characters of A-Z, a-z, 0-9, ".", "_" and "-" (the value is
not shown). Set a unique root access key from Ansible Vault, for example 20
random uppercase letters and digits.
```

**Cause:** the key is not set, is the public default, or contains a
character that breaks SigV4 or the env file (`/`, `=`, `,`, whitespace,
quotes).

**Fix:** generate one, for example
`LC_ALL=C tr -dc 'A-Z0-9' </dev/urandom | head -c 20`, and store it with
`ansible-vault`.

### Validate rustfs_secret_key

**Symptom:** the play stops here with:

```
rustfs_secret_key is empty, shorter than 8 characters, the public upstream
default "rustfsadmin" or equal to rustfs_access_key (the value is not
shown). Set a random root secret key of 40 or more characters from Ansible
Vault.
```

**Cause:** as the message says.

**Fix:** generate one, for example `openssl rand -base64 30` (40
characters), and store it with `ansible-vault`.

### Validate rustfs_rpc_secret

**Symptom:** the play stops here with:

```
rustfs_rpc_secret <value>must be at least 8 characters, not "rustfsadmin"
and not equal to rustfs_secret_key (the value is not shown). Set the same
random secret of 40 or more characters for every node from Ansible Vault
(group_vars).
```

In distributed mode `<value>` reads `is required in distributed mode and `;
on a single node it is empty.

**Cause:** a cluster without an RPC secret, or an RPC secret (on any
topology) that is too short, the default, or equal to the secret key.

**Fix:** set `rustfs_rpc_secret` once for the cluster in `group_vars`, for
example from `openssl rand -base64 30`.

### Validate rustfs_iam_master_key

**Symptom:** the play stops here with:

```
rustfs_iam_master_key <value>must be at least 32 characters without a comma
(the value is not shown). It encrypts IAM data at rest
(RUSTFS_IAM_MASTER_KEY), and a retired key is listed in the comma-separated
RUSTFS_IAM_MASTER_KEY_OLD_KEYS. Set the same random key for every node from
Ansible Vault (group_vars), for example the output of "openssl rand -base64
48".
```

In distributed mode `<value>` reads `is required in distributed mode and `;
on a single node it is empty.

**Cause:** a cluster without an IAM master key, a key (on any topology)
shorter than 32 characters, or a key with a comma: RustFS splits
`RUSTFS_IAM_MASTER_KEY_OLD_KEYS` on commas, so such a key could never be
listed as an old key after a rotation.

**Fix:** set `rustfs_iam_master_key` once for the cluster in `group_vars`
(`openssl rand -base64 48` has no comma). When you replace a key that is
already in use, see [Rotating secrets](../README.md#rotating-secrets).

### Validate the secret values

**Symptom:** the play stops here with:

```
<value>: the value contains a double quote, a backslash or a newline, or
starts or ends with whitespace (the value is not shown). Secrets are
rendered as KEY="value" into secrets.env, where these characters break the
file, and RustFS trims the root keys, the RPC secret and the IAM master key,
so surrounding whitespace would make the vaulted value differ from the one
RustFS uses. Generate the secret without them.
```

`<value>` lists the variable names, for example
`rustfs_secret_key, rustfs_extra_secret_env.RUSTFS_KMS_VAULT_TOKEN`.

**Cause:** a secret with `"`, `\` or a line break (often a trailing newline
from a file lookup), or a root key, RPC secret or IAM master key with a
leading or trailing space. RustFS would use the trimmed value, so clients
with the vaulted value would get `SignatureDoesNotMatch`, and a padded
`rustfsadmin` would pass the default-credential check but be the public
default after trimming.

**Fix:** generate the secret without these characters (base64 output has
none), or strip the trailing newline (`lookup('file', ...)` already does).

### Validate the extra environment keys

**Symptom:** the play stops here with:

```
rustfs_extra_env and rustfs_extra_secret_env must be dicts. Refused keys:
<value>. Keys must match ^[A-Z_][A-Z0-9_]*$, must not start with MINIO_ or
ANSIBLE_RUSTFS_, must not be a key the role sets itself
(__rustfs_reserved_env in vars/main.yml; use the role variable instead, for
example rustfs_iam_master_key for RUSTFS_IAM_MASTER_KEY) and must not be in
both dicts.
```

**Cause:** a list instead of a dict, a lower-case key, a `MINIO_` or
`ANSIBLE_RUSTFS_` key, a key the role owns, or a key in both dicts.

**Fix:** use the role variable for a reserved key (the list is in
[CONFIGURATION.md](CONFIGURATION.md#notes)); keep each key in one dict.

### Validate the extra environment values

**Symptom:** the play stops here with:

```
Values of rustfs_extra_env and rustfs_extra_secret_env must be strings
without a double quote, a backslash or a newline; quote booleans and numbers
("true", "30"). Refused keys: <value> (values not shown).
```

**Cause:** an unquoted YAML boolean or number (`RUSTFS_KMS_ENABLE: true`),
or a value with `"`, `\` or a line break.

**Fix:** quote the value: `RUSTFS_KMS_ENABLE: "true"`.

### Validate rustfs_tls_generate_certs needs rustfs_tls_enabled

**Symptom:** the play stops here with:

```
rustfs_tls_generate_certs is true but rustfs_tls_enabled is false. Enable
TLS, or set rustfs_tls_generate_certs: false.
```

**Cause and fix:** as the message says.

### Validate rustfs_ready_retries and rustfs_ready_delay

**Symptom:** the play stops here with:

```
rustfs_ready_retries (<value>) and rustfs_ready_delay (<value>) must be
integers of at least 1: every wait needs at least one attempt and a pause of
at least one second between attempts.
```

**Cause and fix:** set both to positive integers (defaults 60 and 5).

### Validate this host is in rustfs_cluster_hosts

**Symptom:** the play stops here with:

```
Inventory host '<value>' is not in rustfs_cluster_hosts <value>.
rustfs_cluster_hosts defaults to the 'rustfs' inventory group: put every
node of the cluster in that group, or set rustfs_cluster_hosts to the
inventory names of the cluster.
```

**Cause:** the cluster nodes are in a group with another name, or an
explicit `rustfs_cluster_hosts` misses this host.

**Fix:** put the nodes in the `rustfs` group, or set `rustfs_cluster_hosts`
in the group vars of your group.

### Validate rustfs_node_address is one of the volume hosts

**Symptom:** the play stops here with:

```
rustfs_node_address '<value>' of inventory host '<value>' is not one of the
hosts in rustfs_volumes: <value>. It defaults to inventory_hostname; the
typical cause is short inventory names with FQDN volume hosts. Use the
volume host names in the inventory, or set rustfs_node_address per host
(host_vars) to the name this node has in rustfs_volumes.
```

**Cause:** the inventory names (`rustfs1`) differ from the host names in
`rustfs_volumes` (`rustfs1.example.com`), or the reverse. RustFS finds
itself and its peers through these names, so the role refuses at once
instead of after a readiness timeout.

**Fix:** use the volume host names as inventory names (with `ansible_host`
for the address), or set `rustfs_node_address` per host.

### Validate rustfs_cluster_hosts matches the volume hosts

**Symptom:** the play stops here with:

```
rustfs_cluster_hosts has <value> hosts <value> but rustfs_volumes names
<value> hosts <value>. Every node in rustfs_volumes needs exactly one
inventory host in rustfs_cluster_hosts.
```

**Cause:** the `rustfs` group holds a host that is no RustFS node (a load
balancer, for example), or misses one; or a new pool's nodes are in
`rustfs_volumes` but not yet in the inventory.

**Fix:** make the `rustfs` group exactly the set of nodes in
`rustfs_volumes`.

### Validate the play does not use serial

**Symptom:** the play stops here with:

```
This play runs in batches of <value> of <value> hosts (serial). Remove
serial: the role restarts nodes one at a time itself, and serial breaks the
first bootstrap (every node must start in the same run) and the cluster
consistency check.
```

**Cause:** `serial:` on a play with distributed nodes.

**Fix:** remove `serial`. The role restarts nodes one at a time with health
gates on its own. For day-2 work on one node, `--limit` is fine.

### Validate every cluster host of the play set its fingerprint

**Symptom:** the play stops here with:

```
The cluster hosts <value> of this play have no cluster fingerprint, but
<value> has one, so the cluster cannot be checked for one configuration.
Either they failed an earlier task (a rescued failure keeps a host in the
play), their rustfs_volumes are not URLs, or the play does not use the
default linear strategy: the role compares the hosts of a play with each
other, so remove strategy free or host_pinned from the play and from
ansible.cfg.
```

**Cause:** the next check compares the cluster configuration of all cluster
hosts of the play. Under `strategy: free` or `host_pinned` (in the play or as
`strategy` in `ansible.cfg`) a fast host gets here before the others have
computed theirs, and would compare only with itself; the role refuses that.
The other causes: a host failed an earlier guard inside a `block` with
`rescue` (it stays in the play), or a host of the cluster group has local
paths in `rustfs_volumes`.

**Fix:** run the role with the default linear strategy, fix the host that
failed first, or give every cluster host the cluster's URL volumes.

### Validate one cluster per play

**Symptom:** the play stops here on every host with:

```
The distributed hosts of this play do not share one cluster configuration:
<value> differ from <value>. All nodes of a cluster need identical
rustfs_version, rustfs_libc, rustfs_volumes, rustfs_address port,
rustfs_tls_enabled, rustfs_cluster_hosts, credentials (access key, secret
key, RPC secret, IAM master key), rustfs_extra_env and
rustfs_extra_secret_env. Define them in group_vars, and run one play per
cluster.
```

`<value>` names inventory hosts, never values.

**Cause:** a `host_vars` override of a cluster-wide variable, different
vaulted values per host, or two clusters in one play.

**Fix:** define cluster-wide variables once in `group_vars/rustfs`, and run
one play per cluster.

---

## Host guards (preflight.yml)

These read the host and the running RustFS process before anything is
installed or rendered. The layout guard and the BYO file check also run in
render mode.

### Validate the host runs systemd

**Symptom:** the play stops here with:

```
This host reports the service manager '<value>'
(ansible_facts['service_mgr']). The role runs RustFS as a hardened systemd
unit and supports systemd hosts only.
```

**Cause:** a container or host without systemd as PID 1.

**Fix:** run the role on a systemd host (for containers see the Molecule
platforms in `molecule/default/molecule.yml`).

### Validate glibc for the gnu build

**Symptom:** the play stops here with:

```
rustfs_libc "gnu" needs glibc 2.31 or newer, but this host reports '<value>'
(getconf GNU_LIBC_VERSION). Use rustfs_libc: "musl" (the static build, the
default).
```

**Cause:** the host's glibc is older than 2.31, or the host has no glibc.

**Fix:** use `rustfs_libc: "musl"`.

### Validate the data dirs are mounted drives

**Symptom:** the play stops here with:

```
rustfs_require_mounted_drives is true, but these data dirs are not mount
points: <value>. The role refuses to write object data to the root disk.
Mount a dedicated drive at every path of rustfs_data_dirs first (fstab or a
systemd mount unit), or set rustfs_require_mounted_drives: false on dev/test
hosts only.
```

**Cause:** a drive is not mounted (missing fstab entry, failed mount, a dead
disk, a new host whose drives are not prepared yet). The role would set the
owner of the directory below the mount point and so make the root disk
writable for RustFS. RustFS itself keeps running on the other drives (see
[A drive is offline](#a-drive-is-offline)).

**Fix:** prepare and mount the drives
([INTEGRATION.md](INTEGRATION.md#preparing-the-drives)), check with
`findmnt /data/rustfs0`. A dead disk: replace it as described in
[A drive is offline](#a-drive-is-offline). Use
`rustfs_require_mounted_drives: false` only where losing the data does not
matter.

### Validate the extra read-write paths exist

**Symptom:** the play stops here with:

```
rustfs_systemd_read_write_paths entries <value> do not exist on this host.
systemd refuses to start a unit whose ReadWritePaths entry is missing
(226/NAMESPACE). Create them first (owned by rustfs_user when RustFS writes
there), or remove them from the list.
```

**Cause and fix:** create the directories in a pre-task (they are listed
in the message) or remove them from the list.

### Validate the volume layout is unchanged

**Symptom:** the play stops here with:

```
The storage layout differs from the deployed one: <value>. Nothing was
changed. The pool layout and the erasure set size of an initialised pool
are immutable: RustFS refuses to start on a different layout, and reordered
or resized pools can lose data. The only legitimate volumes change is
appending a pool or removing a decommissioned pool. For that, set
rustfs_allow_volumes_change: true for this run; the changed nodes are then
restarted together.
```

`<value>` shows only what differs, against the env file and, while RustFS
runs, against its process environment, for example
`RUSTFS_VOLUMES in /etc/default/rustfs "...", desired "..."` or
`RUSTFS_VOLUMES in the running process "...", desired "..."`. Without
either, it says that a data dir holds a formatted RustFS drive
(`.rustfs.sys/format.json`) but neither the env file nor a running process
shows the layout it belongs to.

**Cause:** `rustfs_volumes` or `RUSTFS_ERASURE_SET_DRIVE_COUNT` changed by
mistake (a typo, reordered pools, a different range); the host carries an
env file from another installation (the upstream package ships one with
every line commented out, which counts as a different layout); or the env
file is gone (moved with `rustfs_env_file`, a restored host) while the
drives are formatted.

**Fix:** restore the deployed value. For a real pool append or a removal
after a completed decommission, set `rustfs_allow_volumes_change: true` for
that one run. On a host without data that was prepared by another tool,
remove the foreign env file first. When the env file is lost but
`rustfs_volumes` is the layout the drives were formatted with, set
`rustfs_allow_volumes_change: true` once to render it again. A first run
that failed before any node started (nothing formatted) can also need the
override once to correct a typo.

### Validate no unmanaged binary sits at the binary path

**Symptom:** the play stops here with:

```
An unmanaged RustFS binary exists at <value> (<value>). The role manages
<value> as a symlink to <value>/rustfs-<version>-<libc> and never replaces a
binary it did not install. Move it away before running the role (stop the
service that uses it first), or set rustfs_bin_dir to another directory.
```

**Cause:** RustFS was installed by hand or by the upstream install script
into `rustfs_bin_dir`.

**Fix:** stop the service that runs it, move the binary away (keep it until
the role's install works), then run the role. Its env file usually also
needs attention (see the layout guard above).

### Validate rustfs_version is not a downgrade

**Symptom:** the play stops here with:

```
rustfs_version <value> is lower than the installed version <value> (<value>
-> <value>). Upstream documents only an immediate rollback to the previous
release. Read the release notes, then set rustfs_allow_downgrade: true for
the rollback.
```

**Cause:** `rustfs_version` is lower than the version the `rustfs` symlink
points at.

**Fix:** for a rollback to the previous release, set
`rustfs_allow_downgrade: true` for that run; the previous binary is still
installed, so nothing is downloaded and the nodes roll one at a time.

### Validate the first bootstrap includes every cluster host

**Symptom:** the play stops here on every host with:

```
First bootstrap: no host of this play has a formatted drive yet, but the
cluster hosts <value> are not in the play. A new cluster starts only when
every node of rustfs_cluster_hosts runs in the same play (no --limit, no
failed or unreachable hosts). Adding or replacing a node in a running
cluster is also done by running the play against the whole cluster.
```

**Cause:** the first run uses `--limit`, or a node is unreachable or failed
an earlier task. RustFS cannot reach read quorum unless enough nodes start
together, so the role refuses before touching any host. A cluster counts as
bootstrapped once a drive of a host in the play holds
`.rustfs.sys/format.json`, so a retry of a first run that failed after
rendering is still checked.

**Fix:** make every listed host reachable and run the play against the
whole cluster.

### Validate the BYO TLS files are in place

**Symptom:** the play stops here with:

```
TLS is on with operator-supplied material (rustfs_tls_enabled true,
rustfs_tls_generate_certs false), but these files are missing or not regular
files: <value>. The role never creates or copies BYO TLS material: place
rustfs_cert.pem (with a SAN for rustfs_node_address), rustfs_key.pem and,
unless rustfs_tls_trust_system_ca is true, the CA certificate ca.crt in
<value> before running the role, or set rustfs_tls_generate_certs: true on
dev/test hosts.
```

**Cause:** the certificate material is not on the host yet, has another
file name, or is a dangling symlink.

**Fix:** place the files in a pre-task
([INTEGRATION.md](INTEGRATION.md#byo-certificates)).

### Validate cluster-wide changes include every cluster host

**Symptom:** the play stops here with:

```
<value> would change on <value>, but the cluster hosts <value> are not in
this run (--limit, or a host that failed, also inside a block with rescue,
or is unreachable). These keys must change on every node in the same run: a
node with another RPC secret or layout cannot talk to its peers, and nodes
with different credentials or IAM master keys answer differently. Nothing
was changed. Run the play against the whole cluster.
```

The first `<value>` lists key names only, for example `RUSTFS_RPC_SECRET`.

**Cause:** a run that leaves cluster hosts out (`--limit` as a canary, an
unreachable node, or a node that failed an earlier guard) would change
`RUSTFS_VOLUMES`, `RUSTFS_RPC_SECRET`, the root credentials, the IAM master
key or its old keys on some nodes only. A node with a new RPC secret is cut
off from its peers and never becomes ready; nodes with different root
credentials answer the same client differently. A new node that never ran
the role counts as a change too.

**Fix:** run the play against the whole cluster. `--limit` stays fine for
day-2 work that changes none of these keys (a log level, a certificate, a
drive replacement).

### Validate an IAM master key change keeps IAM data readable

**Symptom:** the play stops here with:

```
Refusing the IAM master key change (<value>). Nothing was changed. "old key
dropped": the key the node runs with must stay in
rustfs_extra_secret_env['RUSTFS_IAM_MASTER_KEY_OLD_KEYS'] (a comma-separated
list), or every IAM user, policy and service account encrypted with it
becomes unreadable. "new key unknown": rotate a cluster in two runs, first
with the current rustfs_iam_master_key and the new key in
RUSTFS_IAM_MASTER_KEY_OLD_KEYS, then with the two swapped (README, "Rotating
secrets"). "not checked": the play does not use the default linear strategy.
```

`<value>` lists one problem per host, for example
`rustfs1.example.com: new key unknown; rustfs2.example.com: new key unknown`.

**Cause:** RustFS encrypts IAM data with `RUSTFS_IAM_MASTER_KEY`, decrypts
with it and with `RUSTFS_IAM_MASTER_KEY_OLD_KEYS`, and rewrites every entry
it read with an old key using the current one. "old key dropped": the key
the node runs with (or ran with last) is neither the new key nor listed as
an old key, so IAM data encrypted with it would become unreadable ("IAM
config decrypt failed" in the journal, users fail with `NoSuchUser`).
"new key unknown": in a cluster, the first node restarted with the new key
would rewrite IAM data with it while the other nodes, still running, cannot
decrypt it yet.

**Fix:** follow [Rotating secrets](../README.md#rotating-secrets): keep the
running key in `RUSTFS_IAM_MASTER_KEY_OLD_KEYS`, and in a cluster rotate in
two runs.

---

## Install guard (install.yml)

### Validate the extracted binary reports rustfs_version

**Symptom:** the play stops here with:

```
The binary in <value> reports the versions <value> (<value>), not
rustfs_version <value>. Nothing was installed. Check
rustfs_download_base_url and rustfs_checksum: the mirror may serve a
different release under this name.
```

**Cause:** the downloaded zip passed its checksum (an explicit
`rustfs_checksum`, or a `SHA256SUMS` from the same mirror) but holds
another release.

**Fix:** fix the mirror, and take the digest from the upstream GitHub
release, not from the mirror.

---

## TLS guards (tls_byo.yml and service.yml)

The `tls_byo.yml` checks run after the config stage: a host that fails one
has new files on disk, but its running process was not restarted.

### Validate the BYO TLS certificate is valid now

**Symptom:** the play stops here with:

```
The certificate <value> is expired or not yet valid (not before <value>, not
after <value>). Place a current certificate in <value>.
```

**Cause:** an expired certificate, or the host clock is wrong.

**Fix:** replace `rustfs_cert.pem` (and the key, if it changed). Check the
clock with `timedatectl`. RustFS reloads a replaced certificate that keeps
every name of the served one; otherwise the next run restarts the node
([x509 and TLS errors between peers](#x509-and-tls-errors-between-peers)).

### Validate the BYO TLS certificate allows server authentication

**Symptom:** the play stops here with:

```
The certificate <value> has the extended key usages <value> without
serverAuth ("TLS Web Server Authentication"). RustFS refuses such a server
certificate when it loads it, after a restart has taken the node down. Issue
the node certificate with EKU serverAuth (and clientAuth if your PKI adds
usages), or without an extendedKeyUsage extension.
```

**Cause:** the certificate was issued from a client or other profile of the
PKI. RustFS rejects a server leaf whose extendedKeyUsage extension lacks
serverAuth (`InvalidServerEku`); `rustfs tls inspect` only parses the files
and does not notice.

**Fix:** issue the node certificate from a server profile (EKU serverAuth,
plus clientAuth if wanted).

### Validate the BYO TLS certificate covers rustfs_node_address

**Symptom:** the play stops here with:

```
The certificate <value> does not cover rustfs_node_address '<value>' of host
'<value>': it needs one of <value>, but its SANs are <value>. Peers and the
role's health probes connect to this name. Issue the certificate with that
SAN (in a cluster: this node's host name in rustfs_volumes), or set
rustfs_node_address to a name the certificate covers.
```

**Cause:** the SAN list lacks the node name (the subject CN does not
count). On a single node with a wildcard listener `rustfs_node_address` is
`localhost`.

**Fix:** issue the certificate with the name as a DNS SAN (or IP SAN for an
address), or set `rustfs_node_address` to a covered name that resolves to
the node itself.

### Validate the BYO TLS key belongs to the certificate

**Symptom:** the play stops here with:

```
The private key <value> does not belong to the certificate <value> (their
public keys differ). RustFS refuses to start with a mismatched pair. Place
the key the certificate was issued for, together with the certificate.
```

**Cause:** the certificate was renewed with a new key but only one file was
replaced.

**Fix:** replace both files together. Compare with
`openssl x509 -in rustfs_cert.pem -noout -pubkey` and
`openssl pkey -in rustfs_key.pem -pubout`.

### Validate RustFS finds a usable server certificate

**Symptom:** the play stops here with:

```
RustFS finds no usable server certificate in <value> on <value> (<value> tls
inspect, rc <value>): <value>. Nothing was started or restarted. Place a
valid rustfs_cert.pem and the matching rustfs_key.pem there, or set
rustfs_tls_generate_certs: true on dev/test hosts.
```

**Cause:** `rustfs tls inspect` reports
`runtime mode: no-usable-server-cert` (it exits 0 in that case), or the command failed. The
role checks this right before it would start or restart the node, with the
binary the node is about to run. The command only parses the files; the
`tls_byo.yml` checks above cover validity, SANs, EKU and the key match.

**Fix:** run `/usr/local/bin/rustfs tls inspect --path /etc/rustfs/tls` on
the node and fix what it reports (PEM format, chain order, file names).

---

## Service guard (service.yml)

### Validate the files on disk match the role variables

**Symptom:** the play stops here with:

```
The files on <value> do not match the role variables: keys that differ in
<value> or secrets.env: <value>; versioned binary <value> <value>. A start
or restart loads the files and the binary on disk, so it would not apply the
variables. Nothing was started or restarted. Run the install and config
stages too (no --tags, or --tags install,config,service).
```

`<value>` lists key names only, for example `['RUSTFS_OBS_LOGGER_LEVEL']`,
and says whether the versioned binary `is installed` or `is missing`.

**Cause:** a run with `--tags service` (static role) after a variable
change: the config stage did not render the change, or the install stage
did not install the new version. A restart would start the process from the
old files and binary, and every later run would restart again. Check mode
skips this check (it renders nothing) and reports from the variables.

**Fix:** run without `--tags`, or include the stages that render the change
(`--tags config,service`, `--tags install,config,service`).

---

## Rollout failures (wait_ready.yml and restart_node.yml)

A rollout failure stops the whole play (`any_errors_fatal`). The nodes after
the failing one were not restarted; re-running the play resumes the rollout,
because the role compares every node's running process with the desired
state again.

### Fail with the readiness diagnosis of {{ __rustfs_wait_node }}

**Symptom:** the play stops here with:

```
RustFS on <value> did not become ready within <value> x <value> s: <value>.
Check: every node of a new cluster runs in the same play (no serial, no
--limit); the volume host names resolve on every node (with the musl build
through DNS or /etc/hosts only); the clocks are in sync; the S3 port is
reachable between the nodes; the certificate SANs cover the node names. Last
journal lines: <value>
```

The diagnosis says either `no new main process came up` (RustFS exits at
once and systemd restarts it every 10 s) or which status and body
`/health/ready` answered last; the message ends with the last 50 journal
lines.

**Cause:** see the journal lines. Typical: peers not running or not
reachable on the S3 port, names that do not resolve, clock skew, a
certificate the peers do not trust, an unmounted or shared drive, an
unsupported filesystem.

**Fix:** see [Readiness timeout on the first
bootstrap](#readiness-timeout-on-the-first-bootstrap) and the RustFS error
sections below. On a slow first start (large drives) raise
`rustfs_ready_retries`.

### Validate every peer is ready before restarting {{ __rustfs_node }}

**Symptom:** the play stops here with:

```
refusing to restart <value>: <value>. Nothing was restarted on <value> or
after it. Fix the peer, or set rustfs_rolling_restart: false to restart all
changed nodes together in a maintenance window.
```

The second `<value>` lists each peer that is not ready, joined by `; `, for
example:

```text
peer rustfs4 is not ready (status -1: Status code was -1 and not [200, 503]: Request failed: <urlopen error [Errno 111] Connection refused>)
peer rustfs3 is not ready (status 503: storage_quorum_unavailable)
```

**Cause:** a peer is down, unreachable from the node, degraded, or answers
without `details.storage`. Restarting another node now could cost quorum.

**Fix:** see [A rollout is refused because a peer is
down](#a-rollout-is-refused-because-a-peer-is-down).

### Fail because a drive is offline before restarting {{ __rustfs_node }}

**Symptom:** the play stops here with:

```
refusing to restart <value>: its peers still list drives as unavailable or
missing after <value> x <value> s (<value>). With a drive offline, taking
another node down can cost an erasure set its read or write quorum. Nothing
was restarted on <value> or after it. Bring the drive back or replace it
(TROUBLESHOOTING, "A drive is offline"), or set rustfs_rolling_restart:
false to restart all changed nodes together in a maintenance window.
```

The third `<value>` lists, per peer, the drives it reports as
`poolIndex/setIndex/diskIndex`, for example `rustfs2 (status 200): 0/0/5`.

**Cause:** every peer is ready, but at least one lists a drive as
unavailable or missing for the whole wait. `/health/ready` only follows the
read quorum of the present state; it does not say whether the cluster
survives losing this node's drives as well. In four nodes with four drives
each (one set of 16, parity 4), one dead drive plus a restarting node is
five missing shards, and the set loses read and write quorum while the node
restarts. The role does not compute which layouts survive: it refuses.

**Fix:** see [A drive is offline](#a-drive-is-offline).

### Fail because a peer did not re-admit {{ __rustfs_node }}

**Symptom:** the play stops here with:

```
<value> restarted and is ready, but its peers did not re-admit it within
<value> x <value> s: <value> still list a drive as unavailable or missing.
The rollout stopped here; the nodes after <value> were not restarted. Check
the network between the nodes, then re-run the play to resume.
```

**Cause:** the restarted node reaches the cluster, but the listed peers
still list a drive as unavailable or missing (they cannot reach it, for
example a firewall rule or a changed address, or a drive went offline
during the restart).

**Fix:** check connectivity from the listed peers to the node on the S3
port, then re-run the play.

---

## Download checksum mismatch

**Symptom:** the play stops at `Download the release zip with its SHA-256`
with:

```
The checksum for <value> did not match <value>; it was <value>.
```

or, when the digest comes from `SHA256SUMS` and the asset is not listed:

```
Unable to find a checksum for file '<value>' in '<value>'
```

**Cause:** the asset was replaced upstream after the digest was pinned, the
mirror serves a different or truncated file, `rustfs_checksum` belongs to
another asset (arch or libc), or the mirror's `SHA256SUMS` lacks the asset.
Nothing was installed and the temporary directory was removed.

**Fix:** compare the digest with the `SHA256SUMS` of the GitHub release
(`gh release download 1.0.6 -R rustfs/rustfs -p SHA256SUMS`). Do not just
replace a pinned digest: a changed asset under an existing tag needs an
explanation first.

---

## Readiness timeout on the first bootstrap

**Symptom:** `Fail with the readiness diagnosis of <node>` on the first run;
`/health/ready` answers 503 with `degradedReasons` such as
`storage_quorum_unavailable` or `lock_quorum_unavailable`.

**Cause:** a node of a new cluster becomes ready only when enough peers run.
Typical reasons: not every node was started in this run (`serial`,
`--limit`, a host that failed earlier), the volume host names do not
resolve on every node, the clocks drift, port 9000 is blocked between the
nodes, or the peers do not trust each other's certificates.

**Fix:**

```bash
getent hosts rustfs1.example.com rustfs2.example.com   # on every node
timedatectl show -p NTPSynchronized                     # yes on every node
curl --cacert /etc/rustfs/tls/ca.crt https://rustfs2.example.com:9000/health/live
journalctl -u rustfs -n 100 --no-pager
```

`getent` resolves through NSS (`/etc/nsswitch.conf`: `myhostname`,
`resolve`, `mdns`, `sss` and so on). The default `musl` build of RustFS does
not use NSS: it reads only `/etc/hosts` and the DNS servers in
`/etc/resolv.conf`. A name that `getent` resolves through an NSS module only
does not resolve for RustFS, which then waits in topology detection (180 s,
then it exits and restarts). Check with `grep <name> /etc/hosts` or
`dig +short <name>`, and put the node names in DNS or `/etc/hosts`, or use
`rustfs_libc: "gnu"`.

Then run the play again against the whole cluster.

---

## Distinct physical disks

**Symptom:** the unit restarts every 10 s; the journal shows:

```text
local erasure endpoints must use distinct physical disks; detected shared devices [...]
```

**Cause:** two data dirs of this node resolve to the same block device
(partitions or LVM volumes of one disk, or directories on one filesystem).
RustFS refuses that layout because one disk failure would take out several
erasure shards.

**Fix:** one physical disk per data dir. Only in test environments
(containers, loop devices) set `rustfs_unsafe_bypass_disk_check: true`.

---

## Unsupported filesystem

**Symptom:** the unit restarts every 10 s; the journal shows:

```text
Unsupported filesystem type detected for RustFS local endpoints: ... Startup aborted by policy: RUSTFS_UNSUPPORTED_FS_POLICY=fail
```

**Cause:** a data dir sits on NFS, CIFS, FUSE, overlayfs, 9p, Ceph,
GlusterFS or GFS (for example a container's root filesystem).

**Fix:** use direct-attached local disks (XFS). Containers for tests only:
`rustfs_unsupported_fs_policy: "warn"`.

---

## Unit exits with 226/NAMESPACE

**Symptom:** `systemctl status rustfs` shows `status=226/NAMESPACE`.

**Cause:** an entry of `ReadWritePaths` does not exist when the unit
starts: an extra path from `rustfs_systemd_read_write_paths` or a data dir
that was removed after the run. The role checks the extra paths in preflight
and creates the data dirs, so this happens only when a path disappears
later.

**Fix:** recreate the path (with its owner), or remove it from the variable
and run the play.

---

## A drive is offline

**Symptom:** `/health/ready` of the node that holds the drive lists it under
`details.storage.missingDrives` (or `unavailableDrives`); its peers may list
nothing, because they still see the node online. The role refuses with
`Validate the data dirs are mounted drives` on that node and with
`Fail because a drive is offline before restarting <node>` on the others.

**Cause:** a disk died, a mount failed at boot (`nofail` keeps the boot
going), or a disk was pulled. The unit is ordered after the drive mounts but
does not depend on them, so the node keeps serving on its other drives:
one offline drive, not a node down. RustFS cannot write to the empty
directory below the mount point (root-owned, see
[INTEGRATION.md](INTEGRATION.md#preparing-the-drives)), so no object data
lands on the root disk. A rolling restart now could cost an erasure set its
quorum, so the role does not start one. While the drive is missing,
`/minio/health/cluster` can also answer 503 with `pool_meta_write_blocked`
from time to time (a pool metadata replica is unreadable), and in a cluster
a node that starts without one of its drives can stay in startup for
minutes (`/health/ready` 503 with `startup_finalization_pending`); the
other nodes keep serving.

**Fix:**

1. Mount the drive again, or replace a failed disk with an empty one,
   formatted like the others, at the same path (new UUID in `/etc/fstab`).
2. Restart RustFS on that node (`systemctl restart --no-block rustfs`): a
   filesystem mounted after the start is not visible in the namespace of the
   running process. With an offline drive only on this node, the restart
   costs no more than any node restart. The new filesystem root is still
   `root:root`, so the drive stays listed for now.
3. Run the play for that node (`--limit <node>` is fine: nothing
   cluster-wide changes). It passes the mount guard and sets
   `rustfs:rustfs 0750` on the new filesystem; RustFS notices the writable
   drive within seconds, formats it and heals it.
4. Wait until no node lists the drive any more, the node itself first:

   ```bash
   for n in rustfs1 rustfs2 rustfs3 rustfs4; do
     curl -s --cacert /etc/rustfs/tls/ca.crt "https://$n.example.com:9000/health/ready" \
       | jq -c --arg n "$n" '{node: $n} + (.details.storage | {unavailableDrives, missingDrives})'
   done
   ```

5. Run the play against the whole cluster again for pending changes.

When the change cannot wait for the drive, run in a maintenance window with
`rustfs_rolling_restart: false` (the changed nodes restart together; the
node without the drive still refuses at its mount guard).

---

## PoolTopologyMismatch

**Symptom:** the node never becomes ready; the journal shows:

```text
pool topology mismatch: stored N drives with M drives per erasure set, configured ...
```

**Cause:** the configured volumes or erasure set width differ from what the
drives store in `format.json` (a changed range, reordered pools, a changed
`RUSTFS_ERASURE_SET_DRIVE_COUNT`). The role's layout guard prevents this
unless `rustfs_allow_volumes_change` was set or the env file was edited by
hand.

**Fix:** restore the original `rustfs_volumes` and set width (run once with
`rustfs_allow_volumes_change: true` to render them back). Never delete
`format.json` or anything under `.rustfs.sys` to get past the error.

---

## x509 and TLS errors between peers

**Symptom:** the readiness diagnosis or the journal shows TLS handshake
errors between nodes, such as rustls `UnknownIssuer` or `NotValidForName`.

**Cause:** `UnknownIssuer`: the peer's certificate is signed by a CA that is
neither in `ca.crt` (or `public.crt`) of the TLS directory nor, with
`rustfs_tls_trust_system_ca: true`, in the OS store (it only adds the OS
store to `ca.crt`). `NotValidForName`: the peer's certificate lacks a SAN for
the host name it has in `rustfs_volumes`.

**Fix:** put the CA that signed every node certificate into `ca.crt` on
every node, and issue each node certificate with its volume host name as a
DNS SAN. Check with:

```bash
openssl verify -CAfile /etc/rustfs/tls/ca.crt /etc/rustfs/tls/rustfs_cert.pem
openssl s_client -connect rustfs2.example.com:9000 -CAfile /etc/rustfs/tls/ca.crt \
  -servername rustfs2.example.com </dev/null
```

RustFS reloads replaced certificate files within 30 s
(`RUSTFS_TLS_RELOAD_INTERVAL`), but only when the new certificate keeps
every name of the one it serves and no material file was removed; otherwise
it logs `TLS material update rejected` at WARN and keeps the old
certificate. The role compares the served certificate with the file on
every run and restarts the node (reason `tls`, in the rolling order) when
the reload did not happen within one interval.

---

## 503 with Retry-After during a rollout

**Symptom:** during a rolling restart some S3 requests get HTTP 503 with
`Retry-After: 5` and `x-rustfs-readiness-pending`.

**Cause:** the request reached the node that is restarting, which answers
503 until it is ready again. This is expected; one node at a time is down.

**Fix:** S3 SDKs retry 503 by themselves. Put a load balancer in front that
health-checks `/health/ready`, so it stops sending traffic to the restarting
node ([INTEGRATION.md](INTEGRATION.md#haproxy-in-front-of-the-cluster)).

---

## A rollout is refused because a peer is down

**Symptom:** `Validate every peer is ready before restarting <node>` fails
and names the peer.

**Cause:** a rolling restart takes one node down at a time; with another
node already down it could cost read or write quorum, so the role refuses
before it restarts anything.

**Fix:** bring the peer back (include it in the play: the role starts a node
that is down, waits for it, then rolls the others). If the peer is gone for
good and the change cannot wait, run in a maintenance window with
`rustfs_rolling_restart: false`: the reachable changed nodes restart
together.

---

## Hosts stay failed after a rescued rollout

**Symptom:** a playbook wraps the role in `block`/`rescue`; after a refused
rollout every host shows `failed=0` in the recap, but later plays skip some
hosts and the playbook exits with status 2.

**Cause:** the rollout block uses `any_errors_fatal`. ansible-core keeps
the hosts it aborted for that reason in its failed-host list even after a
rescue.

**Fix:** end the rescuing play with `ansible.builtin.meta: clear_host_errors`.

---

## Restarting a node by hand

The role restarts nodes only when their running state differs from the
desired state. For a manual restart (for example after a kernel update), do
one node at a time:

```bash
# 1. Every node is ready before you start.
for n in rustfs1 rustfs2 rustfs3 rustfs4; do
  curl -s -o /dev/null -w "$n %{http_code}\n" --cacert /etc/rustfs/tls/ca.crt \
    "https://$n.example.com:9000/health/ready"
done

# 2. Restart the node without blocking (a blocking start waits for quorum).
systemctl restart --no-block rustfs

# 3. Wait until the node is ready again.
until curl -sf --cacert /etc/rustfs/tls/ca.crt \
    https://rustfs1.example.com:9000/health/ready >/dev/null; do sleep 5; done

# 4. Wait until every peer stops listing the node's drives as unavailable,
#    then continue with the next node.
curl -s --cacert /etc/rustfs/tls/ca.crt https://rustfs2.example.com:9000/health/ready \
  | jq '.details.storage | {unavailableDrives, missingDrives}'
```

---

## Useful commands

```bash
# Service status and logs
systemctl status rustfs
journalctl -u rustfs -n 100 --no-pager

# Running binary, and the names of the variables the process started with
# (names only: the values include the secrets)
readlink /proc/$(systemctl show rustfs -p MainPID --value)/exe
tr '\0' '\n' < /proc/$(systemctl show rustfs -p MainPID --value)/environ | cut -d= -f1 | sort

# Health (node readiness, cluster write quorum, console)
curl -s --cacert /etc/rustfs/tls/ca.crt https://rustfs1.example.com:9000/health/ready | jq .
curl -s -o /dev/null -w '%{http_code}\n' --cacert /etc/rustfs/tls/ca.crt \
  https://rustfs1.example.com:9000/minio/health/cluster
curl -s -o /dev/null -w '%{http_code}\n' --cacert /etc/rustfs/tls/ca.crt \
  https://rustfs1.example.com:9001/rustfs/console/health

# TLS material as RustFS sees it, and the certificate SANs
/usr/local/bin/rustfs tls inspect --path /etc/rustfs/tls
openssl x509 -in /etc/rustfs/tls/rustfs_cert.pem -noout -subject -ext subjectAltName -enddate

# Rendered configuration (secrets.env is root-only and holds the secrets)
cat /etc/default/rustfs
systemd-analyze verify /etc/systemd/system/rustfs.service
systemd-analyze security rustfs

# Mount points of the data dirs
findmnt -T /data/rustfs0
```
