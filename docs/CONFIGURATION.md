# Configuration Reference

Full variable reference for the RustFS role. All 44 variables are defined with
their defaults in [`defaults/main.yml`](../defaults/main.yml) and validated by
[`meta/argument_specs.yml`](../meta/argument_specs.yml) (role argument
validation) and by `tasks/validate.yml` (cross-variable rules). Every public
variable is prefixed `rustfs_`.

---

## Table of Contents

- [Install](#install)
- [Paths / users](#paths--users)
- [Storage / topology](#storage--topology)
- [Listener / console](#listener--console)
- [Credentials](#credentials)
- [TLS](#tls)
- [Logging / extra environment](#logging--extra-environment)
- [systemd](#systemd)
- [Service control](#service-control)
- [Notes](#notes)

---

## Install

| Variable | Default | Description |
|---|---|---|
| `rustfs_version` | `"1.0.6"` | Pinned RustFS version, bare SemVer without a `v` prefix (the upstream tag format). Bumping it installs a new versioned binary next to the old one and rolls the cluster node by node. A lower version is refused unless `rustfs_allow_downgrade` is true. |
| `rustfs_libc` | `"musl"` | Build flavour of the release asset. Choices: `musl` (static binary, no glibc needed; resolves host names through `/etc/hosts` and the DNS servers of `/etc/resolv.conf` only, never through NSS modules such as `myhostname`, `resolve`, `mdns` or `sss`), `gnu` (needs glibc >= 2.31 on the target, checked in preflight; resolves through NSS; adds profiling support). |
| `rustfs_arch` | `"{{ {'x86_64': 'x86_64', 'amd64': 'x86_64', 'aarch64': 'aarch64', 'arm64': 'aarch64'}.get(ansible_facts['architecture'], '') }}"` | Arch token of the release asset, mapped from `ansible_facts['architecture']`. Any other architecture resolves to `""` and is refused (upstream ships `x86_64` and `aarch64` only). |
| `rustfs_download_base_url` | `"https://github.com/rustfs/rustfs/releases/download"` | Download base URL. The role appends `/<version>/<asset>`, so a mirror must keep that layout, and must also serve `SHA256SUMS` there when neither a pinned digest nor `rustfs_checksum` covers the version. A plain `http://` URL is refused unless a pinned digest or `rustfs_checksum` covers the version. |
| `rustfs_checksum` | `""` | Expected SHA-256 of the release zip (64 lowercase hex characters, no `sha256:` prefix). Empty: the digest pinned in `vars/main.yml` for the default version, otherwise the `SHA256SUMS` file next to the asset. Set it for air-gapped mirrors. |
| `rustfs_bin_dir` | `"/usr/local/bin"` | Directory for the versioned binary (`rustfs-<version>-<libc>`) with its digest file (`rustfs-<version>-<libc>.sha256`), the `rustfs` symlink and the temporary download directory. It must exist and allow execution; it may be a symlink. |
| `rustfs_allow_downgrade` | `false` | Allow installing a version lower than the installed one. Upstream documents only an immediate rollback to the previous release. |

---

## Paths / users

| Variable | Default | Description |
|---|---|---|
| `rustfs_user` | `"rustfs"` | Service user (system account, shell `/usr/sbin/nologin`). Do not change it after the first bootstrap: ownership is never set recursively. |
| `rustfs_group` | `"rustfs"` | Service group. Same rule as `rustfs_user`. |
| `rustfs_home` | `"/opt/rustfs"` | Home and working directory of the service (`rustfs:rustfs 0750`). |
| `rustfs_config_dir` | `"/etc/rustfs"` | Directory that holds `secrets.env` and, by default, the TLS directory (`root:rustfs 0750`). |
| `rustfs_env_file` | `"/etc/default/rustfs"` | Non-secret environment file read by the unit, the upstream path on both OS families (`root:rustfs 0640`, a backup is kept on every change). Secrets never go here; they go to `<rustfs_config_dir>/secrets.env` (`root:root 0600`). |
| `rustfs_tls_dir` | `"{{ rustfs_config_dir }}/tls"` | TLS directory (`RUSTFS_TLS_PATH`, `root:rustfs 0750`). File names inside are fixed by RustFS: `rustfs_cert.pem`, `rustfs_key.pem` and `ca.crt`. |

---

## Storage / topology

| Variable | Default | Description |
|---|---|---|
| `rustfs_volumes` | `[]` | **REQUIRED.** One upstream volume expression per server pool, rendered space-joined as `RUSTFS_VOLUMES`. Identical on every node, pool order included. Ranges use three dots: `["/data/rustfs{0...3}"]` (single node, four drives) or `["https://rustfs{1...4}.example.com:9000/data/rustfs{0...3}"]` (cluster). Immutable once the cluster is bootstrapped (see `rustfs_allow_volumes_change`). |
| `rustfs_data_dirs` | `"{{ __rustfs_volume_paths }}"` | Local drive paths on this host, derived from the path part of `rustfs_volumes`. Override per host only when pools use different paths. Each entry gets `rustfs:rustfs 0750` on the directory itself, never recursively. |
| `rustfs_require_mounted_drives` | `true` | Refuse to continue unless every data dir is a mount point (the role sets the owner of mounted filesystem roots only), and order the unit after the mount unit of every data dir without depending on it. A drive that fails to mount at boot or disappears later is one offline drive: the node keeps serving on its other drives, and the root-owned directory below the mount point is not writable for RustFS ([INTEGRATION.md](INTEGRATION.md#preparing-the-drives)). Set `false` only for dev/test; the role then creates the directories on whatever filesystem holds them. |
| `rustfs_allow_volumes_change` | `false` | Allow `RUSTFS_VOLUMES` or `RUSTFS_ERASURE_SET_DRIVE_COUNT` to differ from the deployed env file for one run. Only for appending a pool or removing a decommissioned one; the changed nodes are restarted together. |
| `rustfs_unsupported_fs_policy` | `"fail"` | What RustFS does when a drive sits on NFS, CIFS, FUSE, overlayfs, 9p, Ceph, GlusterFS or GFS. Choices: `fail` (refuse to start), `warn` (log and continue). |
| `rustfs_unsafe_bypass_disk_check` | `false` | Skip the upstream check that every local drive is a distinct physical disk. Test environments only (containers, loop devices); never in production. |
| `rustfs_cluster_hosts` | `"{{ (groups['rustfs'] \| default([inventory_hostname])) if __rustfs_distributed else [inventory_hostname] }}"` | Inventory hosts that form this node's cluster. In distributed mode the `rustfs` inventory group: used for the consistency checks, the CA host of generated certificates and the peer health checks. A standalone node is its own cluster. |
| `rustfs_node_address` | `"{{ inventory_hostname if __rustfs_distributed else (__rustfs_listen_host if __rustfs_listen_host not in ['', '0.0.0.0', '::'] else 'localhost') }}"` | Name or IP under which the role probes this node's S3 port. In a cluster it must be the host name this node has in `rustfs_volumes`; with TLS the certificate must cover it. Default: `inventory_hostname` in a cluster, else the listen host of `rustfs_address`, or `localhost` for a wildcard listener. |

---

## Listener / console

| Variable | Default | Description |
|---|---|---|
| `rustfs_address` | `":9000"` | S3, admin, health and internode listener, `[host]:port` (`":9000"`, `"10.0.0.11:9000"`, `"[fd00::11]:9000"`). Same port on every node; there is no separate cluster port. A port below 1024 adds `CAP_NET_BIND_SERVICE` to the unit. |
| `rustfs_console_enabled` | `true` | Serve the web console. |
| `rustfs_console_address` | `":9001"` | Console listener, `[host]:port`. It listens on all interfaces by default: bind it to a management address or firewall it. Must not use the S3 port. |
| `rustfs_server_domains` | `[]` | Domains for virtual-hosted-style requests, rendered comma-joined as `RUSTFS_SERVER_DOMAINS`. Empty: path-style requests only. The value must match the `Host` header clients send; add the port only when clients use a port other than the listener's. |

---

## Credentials

All four are secrets: source them from Ansible Vault, define them once for
the cluster in `group_vars`, and never inline them. They are rendered into
`secrets.env` only and are part of the cluster fingerprint.

| Variable | Default | Description |
|---|---|---|
| `rustfs_access_key` | `""` | **REQUIRED.** Root access key, 3 to 128 characters of `A-Z a-z 0-9 . _ -`. The public upstream default `rustfsadmin` is refused. Recommended: 20 random uppercase letters and digits. Changing it is a rolling restart. |
| `rustfs_secret_key` | `""` | **REQUIRED.** Root secret key, at least 8 characters, not `rustfsadmin` and not equal to the access key; no `"`, `\` or newline and no leading or trailing whitespace (RustFS trims it). Recommended: 40 or more random characters. Changing it is a rolling restart and invalidates STS sessions signed with the old key. |
| `rustfs_rpc_secret` | `""` | Internode RPC secret. **REQUIRED in distributed mode** and identical on all nodes; at least 8 characters, not `rustfsadmin`, not equal to the secret key and without surrounding whitespace. An explicit secret keeps internode authentication independent of the root credentials, so those can be rotated with a rolling restart. Changing it restarts the cluster together (old and new secret cannot authenticate each other). |
| `rustfs_iam_master_key` | `""` | IAM master key, rendered as `RUSTFS_IAM_MASTER_KEY`. It encrypts IAM users, policies and service-account secrets at rest; without it they are stored in plaintext on the drives and MFA enrollment is refused. **REQUIRED in distributed mode**, recommended everywhere; at least 32 characters, no comma, no surrounding whitespace. A change must keep the key the nodes run with in `rustfs_extra_secret_env['RUSTFS_IAM_MASTER_KEY_OLD_KEYS']` (a comma-separated list), and a cluster rotates in two runs (preflight refuses anything else, see [README, "Rotating secrets"](../README.md#rotating-secrets)); each run is a rolling restart. |

---

## TLS

TLS is **on by default** and covers the S3, console and internode traffic with
one certificate per node. Two modes:

- **BYO (production, `rustfs_tls_generate_certs: false`, the default):** place
  `rustfs_cert.pem` (full chain, leaf first), `rustfs_key.pem` and `ca.crt` in
  `rustfs_tls_dir` before the run. The role never creates or copies them; it
  checks them (see [Notes](#notes)) and sets their owner and mode.
- **Generated (dev/test, `rustfs_tls_generate_certs: true`):** the role builds
  a private CA on the first cluster host and a node certificate per host with
  `community.crypto`. **The CA private key is copied to every node.**

RustFS reloads replaced certificate files within one reload interval
(`RUSTFS_TLS_RELOAD_ENABLE` is always on; `RUSTFS_TLS_RELOAD_INTERVAL`,
30 s), but only when the new certificate keeps every name of the one it
serves and no material file was removed; otherwise it keeps serving the old
certificate. The role compares the served certificate with
`rustfs_cert.pem` on every run and restarts the node (reason `tls`, rolling)
when the reload did not happen within one interval, for example after a SAN
was removed from `rustfs_tls_extra_sans` or a renewal dropped a name. A
renewal that keeps every name restarts nothing.

| Variable | Default | Description |
|---|---|---|
| `rustfs_tls_enabled` | `true` | TLS on the S3, console and internode traffic. Decide before the first bootstrap: it changes the volume scheme (`https://` vs `http://`), which is part of the immutable layout. |
| `rustfs_tls_generate_certs` | `false` | Generate a private CA (ECC P-384, 10 years, renewed 90 days before expiry) and node certificates (SANs: `rustfs_node_address`, `inventory_hostname`, `localhost`, `127.0.0.1` and `rustfs_tls_extra_sans`; EKU serverAuth and clientAuth). Dev/test only. Requires `rustfs_tls_enabled`. |
| `rustfs_tls_cert_validity` | `"+825d"` | Validity of generated node certificates (community.crypto relative time). A node certificate is re-signed 30 days before it expires, when its SANs or key change, or when the CA changes. |
| `rustfs_tls_extra_sans` | `[]` | Extra SANs for generated certificates, already prefixed (`"DNS:s3.example.com"`, `"IP:10.0.0.10"`), for example a load balancer name. |
| `rustfs_tls_trust_system_ca` | `false` | Also trust the OS CA store for outbound and peer connections (`RUSTFS_TRUST_SYSTEM_CA`), in addition to `ca.crt` (and `public.crt`) in `rustfs_tls_dir`, which stay trusted. The role's health probes use `ca.crt` whenever it exists, else the OS store, so with both `ca.crt` must hold the CA of the node certificates. When false, `ca.crt` is required. |

---

## Logging / extra environment

| Variable | Default | Description |
|---|---|---|
| `rustfs_log_level` | `"info"` | Log level (`RUSTFS_OBS_LOGGER_LEVEL`). Choices: `trace`, `debug`, `info`, `warn`, `error`. Upstream defaults to `error`; `info` shows startup and readiness progress, which the readiness failure message quotes from the journal. Logs always go to journald. |
| `rustfs_extra_env` | `{}` | Extra non-secret variables rendered into the env file, as a dict of string values (quote booleans and numbers: `"true"`, `"30"`). Must be identical on every node of a cluster. Keys the role owns are refused (see [Notes](#notes)). |
| `rustfs_extra_secret_env` | `{}` | Extra secret variables rendered into `secrets.env`, for example a KMS token, an OIDC client secret or `RUSTFS_IAM_MASTER_KEY_OLD_KEYS`. Same rules as `rustfs_extra_env`; a key must not be in both dicts. |

---

## systemd

| Variable | Default | Description |
|---|---|---|
| `rustfs_systemd_read_write_paths` | `[]` | Extra writable paths under the `ProtectSystem=strict` sandbox (`ReadWritePaths`), for example a KMS key directory, notification queue directories or a log directory. Every path must already exist (checked in preflight; a missing path fails the unit with 226/NAMESPACE) and must not be under `/tmp`, `/var/tmp`, `/home`, `/root` or `/run/user`. |

---

## Service control

| Variable | Default | Description |
|---|---|---|
| `rustfs_service_enabled` | `true` | Enable the unit at boot. |
| `rustfs_service_state` | `"started"` | Desired service state. Choices: `started`, `stopped`. A node that is to be stopped is never restarted. |
| `rustfs_rolling_restart` | `true` | Restart changed nodes one at a time, each only when every peer is ready and lists every drive online, and the next only after every peer lists every drive online again. `false` restarts all changed nodes together (a maintenance window, or a node or drive that is permanently down and blocks the rolling path). |
| `rustfs_ready_retries` | `60` | Attempts for every wait: new main process, `/health/ready`, every drive online before and after a rolling restart, and the write-quorum gate. At least 1. |
| `rustfs_ready_delay` | `5` | Seconds between attempts of every wait. At least 1. The default gives each wait 5 minutes. |
| `rustfs_config_only` | `false` | Render-only mode: skip the host guards, install and service management. Used by the `render` Molecule scenario to validate templates offline. |

---

## Notes

- **`become: true` at the play level.** The role does not set `become` on
  individual tasks; the consuming play must declare it. The daemon-reload
  handler and the service tasks need root.
- **BYO TLS checks happen in three places.** Preflight (before anything is
  touched) asserts that `rustfs_cert.pem`, `rustfs_key.pem` and, unless
  `rustfs_tls_trust_system_ca` is true, `ca.crt` are regular files (symlinks
  are followed). After the config stage, `tls_byo.yml` sets the key to
  `root:<rustfs_group> 0640` and the certificate and CA to `root:root 0644`,
  and asserts that the certificate is valid now, that an extendedKeyUsage
  extension, when present, includes serverAuth (RustFS refuses the leaf
  otherwise), that its SANs cover `rustfs_node_address` (`DNS:<name>`, a
  one-label wildcard `DNS:*.<parent>`, or `IP:<address>`; case-insensitive,
  no CN fallback) and that the key belongs to the certificate. Right before
  any start or restart, `rustfs tls inspect` must find a usable server
  certificate (it only parses the files). A host that fails a TLS check after
  the config stage has new files on disk, but its running process is not
  restarted.
- **Volume syntax** (`rustfs_volumes`):
  - Ranges use three dots, `{0...3}`; `{0..3}` is shell syntax and refused.
  - Every list item is one server pool. With more than one item, or with URL
    items, every item must contain a range. A single local plain path
    (`/data/rustfs0`) is the single-drive layout and can never gain a pool;
    start with at least two drives if the node may grow.
  - The host part and the path part may each hold at most one decimal range
    `{N...M}` with N <= M. A start that begins with `0` and is longer than
    one digit zero-pads every value to the length of the end
    (`{01...12}` gives `01` to `12`). Hex ranges are not supported by the
    role.
  - All items are local paths or all are URLs. URLs use `https://` when TLS
    is on and `http://` when it is off, and an explicit port must equal the
    port of `rustfs_address`.
  - The host names in the URLs are the node addresses: each must resolve
    identically on every node (DNS or `/etc/hosts`), and in the default
    setup they equal the inventory names of the `rustfs` group.
  - The erasure set width is chosen by RustFS; pin it with
    `RUSTFS_ERASURE_SET_DRIVE_COUNT` in `rustfs_extra_env` only before the
    first bootstrap, because the layout guard treats it as part of the
    immutable layout.
- **Host prerequisites the role does not manage.** Upstream documents four
  kernel parameters for RustFS hosts; set them with your base-OS tooling
  (for example `ansible.posix.sysctl` into `/etc/sysctl.d/90-rustfs.conf`):

  ```
  net.core.rmem_max = 16777216
  net.core.wmem_max = 16777216
  net.ipv4.tcp_keepalive_time = 600
  net.ipv4.tcp_slow_start_after_idle = 0
  ```

  Clocks must be synchronised (chrony or systemd-timesyncd): request
  signing and distributed locks depend on it; upstream recommends less than
  one second of drift and allows at most 15 minutes between nodes. Drives
  are XFS, one filesystem per
  physical disk, mounted through `/etc/fstab` (see
  [INTEGRATION.md](INTEGRATION.md#preparing-the-drives)).
- **Reserved environment keys.** `rustfs_extra_env` and
  `rustfs_extra_secret_env` refuse keys that do not match
  `^[A-Z_][A-Z0-9_]*$`, keys that start with `MINIO_` (RustFS maps some
  `MINIO_*` names itself) or `ANSIBLE_RUSTFS_` (the role's markers), keys
  that are in both dicts, and the keys the role sets itself:
  `RUSTFS_VOLUMES`, `RUSTFS_ADDRESS`, `RUSTFS_CONSOLE_ENABLE`,
  `RUSTFS_CONSOLE_ADDRESS`, `RUSTFS_SERVER_DOMAINS`, `RUSTFS_ACCESS_KEY`,
  `RUSTFS_SECRET_KEY`, `RUSTFS_ACCESS_KEY_FILE`, `RUSTFS_SECRET_KEY_FILE`,
  `RUSTFS_ROOT_USER`, `RUSTFS_ROOT_PASSWORD`, `RUSTFS_RPC_SECRET`,
  `RUSTFS_IAM_MASTER_KEY`, `RUSTFS_TLS_PATH`, `RUSTFS_TLS_RELOAD_ENABLE`,
  `RUSTFS_TRUST_SYSTEM_CA`, `RUSTFS_TLS_KEYLOG`, `RUSTFS_SERVER_MTLS_ENABLE`
  (the role's health probes have no client certificate),
  `RUSTFS_OBS_LOGGER_LEVEL`, `RUSTFS_OBS_LOG_STDOUT_ENABLED`,
  `RUSTFS_CHECK_UPDATE` (always `"false"`: no update check against
  `version.rustfs.com`), `RUSTFS_UNSUPPORTED_FS_POLICY`,
  `RUSTFS_UNSAFE_BYPASS_DISK_CHECK`, `RUSTFS_HEALTH_ENDPOINT_ENABLE`,
  `RUSTFS_HEALTH_MINIMAL_RESPONSE_ENABLE` (the rollout reads the health
  details) and `RUST_LOG` (it would override the log level).
  `RUSTFS_IAM_MASTER_KEY_OLD_KEYS` stays allowed in `rustfs_extra_secret_env`
  for key rotation. Never set the upstream "version floor" gates
  (`RUSTFS_DATA_MOVEMENT_PART_CHECKSUMS_*`, `RUSTFS_POOL_META_V2_*`,
  `RUSTFS_POOL_META_V3_*`) while nodes run different versions.
- **Logging to files.** Logs always reach journald. For rotating log files
  in addition, create the directory (owned by `rustfs_user`, mode `0750`)
  before the run and set:

  ```yaml
  rustfs_extra_env:
    RUSTFS_OBS_LOG_DIRECTORY: "/var/log/rustfs"
  rustfs_systemd_read_write_paths:
    - "/var/log/rustfs"
  ```

  RustFS rotates, compresses and prunes its own files
  (`RUSTFS_OBS_LOG_ROTATION_TIME`, `RUSTFS_OBS_LOG_KEEP_FILES`,
  `RUSTFS_OBS_LOG_MAX_TOTAL_SIZE_BYTES`); no logrotate configuration is
  needed. The journal copy stays on, because `RUSTFS_OBS_LOG_STDOUT_ENABLED`
  is reserved and always `"true"`.
- **Journal volume at `info`.** Measured in the four-node `distributed`
  scenario while idle: 14 lines per minute on the nodes that hold the
  leader lock (mostly `remote refresh for .rustfs.sys/leader.lock`), 2 per
  minute on the others. Use `warn` if that is still too much.
- **Why `TimeoutStartSec=infinity`.** RustFS reports `READY=1` to systemd
  only after it has read and lock quorum, so a node of a cold cluster stays
  in "activating" until enough peers run. A node that waits for its peers
  stays alive and recovers by itself (upstream: "Do not restart-loop
  them"); a finite start timeout would kill and restart it every
  `TimeoutStartSec` plus `RestartSec`. RustFS bounds its own topology wait
  (180 s on unresolvable peers, then it exits and `Restart=always` starts it
  again), and the Ansible run is bounded by `rustfs_ready_retries` x
  `rustfs_ready_delay`. Side effect: a manual `systemctl start rustfs`
  without `--no-block` blocks until the node is ready. Boot does not wait
  for it: the unit sets `DefaultDependencies=no` (and restores the service
  defaults explicitly), so `multi-user.target` is not ordered after it, and
  units such as cloud-init's final stage or
  `systemctl is-system-running --wait` are not held up by a node that waits
  for its peers.
- **Data dirs without mounts.** With `rustfs_require_mounted_drives: false`
  the role creates missing data dirs, and the file module creates missing
  parents with the same owner and mode (`/data` becomes
  `rustfs:rustfs 0750` when it did not exist). With mounted drives the mount points exist,
  so no parent is created.
- **Removing old binaries.** Every version stays installed as
  `<rustfs_bin_dir>/rustfs-<version>-<libc>` (about 250 to 380 MB each),
  next to `rustfs-<version>-<libc>.sha256`, the digest the role recorded
  when it installed the verified binary, so that a rollback is only a
  variable change. The role never deletes them. A versioned binary without
  its digest file, or with another digest, is downloaded and verified again.
  List them and remove the ones you no longer need (with their digest
  files), but keep the one the symlink points at and the previous one:

  ```bash
  readlink /usr/local/bin/rustfs
  ls -l /usr/local/bin/rustfs-*-*
  rm /usr/local/bin/rustfs-1.0.4-musl /usr/local/bin/rustfs-1.0.4-musl.sha256
  ```
