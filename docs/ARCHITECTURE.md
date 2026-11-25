# Architecture

This document describes the RustFS topology the role deploys, how one run
flows, how the role decides when and how to restart nodes, and what the
Molecule scenarios proved about the systemd sandbox.

---

## Topologies

The role deploys three upstream topologies with one variable interface:
single node single drive (SNSD, `["/data/rustfs0"]`), single node multiple
drives (SNMD, `["/data/rustfs{0...3}"]`) and multiple nodes multiple drives
(MNMD, `["https://rustfs{1...4}.example.com:9000/data/rustfs{0...3}"]`). The
picture shows MNMD with four nodes and an optional load balancer; SNSD and
SNMD are the same picture with a single node and no internode traffic.

```mermaid
flowchart TD
    subgraph clients["S3 clients: Loki, Velero, Terraform, aws CLI, rc"]
        C1[Client 1]
        C2[Client 2]
    end

    Ops["Operators (web console)"]

    LB["Optional HAProxy + keepalived VIP<br/>health check GET /health/ready on every node"]

    subgraph cluster["RustFS cluster: inventory group rustfs, one erasure-coded pool"]
        direction LR
        N1["rustfs1<br/>:9000 S3, admin, health, internode<br/>:9001 console<br/>/data/rustfs0..3"]
        N2["rustfs2<br/>:9000, :9001<br/>/data/rustfs0..3"]
        N3["rustfs3<br/>:9000, :9001<br/>/data/rustfs0..3"]
        N4["rustfs4<br/>:9000, :9001<br/>/data/rustfs0..3"]
        N1 <-->|"internode RPC<br/>TLS :9000"| N2
        N2 <-->|"internode RPC<br/>TLS :9000"| N3
        N3 <-->|"internode RPC<br/>TLS :9000"| N4
    end

    C1 --> LB
    C2 --> LB
    LB -->|"S3 :9000, any ready node"| cluster
    Ops -.->|":9001, management network only"| cluster
```

**Key design points:**

- **One port per node for everything but the console.** `rustfs_address`
  (`:9000`) serves S3, the admin API, the health endpoints and the
  internode RPC; it must be the same port on every node, and every node
  talks to every other node on it (the picture shows neighbours only). The console has
  its own listener (`rustfs_console_address`, `:9001`), which listens on all
  interfaces by default: bind it to a management address or firewall it.
- **One volume string for the whole cluster.** `rustfs_volumes` is rendered
  into `RUSTFS_VOLUMES` byte for byte on every node. The host names in it
  are the node addresses: by default they equal the inventory names of the
  `rustfs` group, which is also `rustfs_cluster_hosts`. The role refuses a
  play in which a node's cluster-wide variables differ (fingerprint), and
  refuses a changed layout on a running cluster (layout guard).
- **One certificate per node.** It serves S3, console and internode traffic
  and needs a SAN for the node's host name in `rustfs_volumes`. Peers trust
  each other through `ca.crt` in `rustfs_tls_dir` (`rustfs_tls_trust_system_ca`
  adds the OS store). RustFS reloads a replaced certificate by itself when
  it keeps every name of the served one; when the reload is rejected, the
  role restarts the node in the rolling order.
- **The load balancer is optional.** Clients can talk to any node. A load
  balancer that health-checks `/health/ready` stops sending traffic to a
  node while it restarts. See
  [INTEGRATION.md](INTEGRATION.md#haproxy-in-front-of-the-cluster).
- **Erasure coding is per pool.** RustFS picks the erasure set width and the
  parity from the drive count of each pool. How many node failures a pool
  survives depends on how its sets spread over the nodes, not only on the
  parity. Upstream documents a minimum of four nodes for MNMD; the role does
  not assert it, because the binary validates smaller layouts itself.
- **Drives are mount points, and a lost drive is one offline drive.** Every
  data dir must be a mounted drive when the role runs
  (`rustfs_require_mounted_drives`), so the role sets the owner of mounted
  filesystem roots only. The unit is ordered after the mounts but does not
  depend on them: after a reboot with a failed mount, or when a disk drops
  out, the node keeps serving on its other drives, and the root-owned
  directory below the mount point is not writable for RustFS, so no object
  data lands on the root disk.

---

## Run sequence

One run of the role against a new four-node cluster. All hosts run every
task in parallel (the default linear strategy); `serial` is refused.

```mermaid
sequenceDiagram
    participant Ctrl as Ansible controller
    participant N1 as rustfs1 (CA host in generated mode)
    participant Nx as rustfs2..4

    Note over Ctrl,Nx: 1. Guards (tag always, read only, render mode too)
    Ctrl->>N1: validate.yml: variables, play shape, cluster fingerprint
    Ctrl->>Nx: validate.yml
    Ctrl->>N1: preflight.yml: systemd, glibc, mounts, extra paths, probe MainPID, /proc/PID/exe and environ, layout, binary, first bootstrap, BYO files, cluster-wide changes, IAM key change
    Ctrl->>Nx: preflight.yml

    Note over Ctrl,Nx: 2. Install, config, TLS
    Ctrl->>N1: install.yml: user, deps, verified versioned binary and its digest file
    Ctrl->>Nx: install.yml
    Ctrl->>N1: config.yml: directories, secrets.env, unit, env file
    Ctrl->>Nx: config.yml
    Ctrl->>N1: tls.yml: BYO checks, or generate the CA and a node certificate
    Ctrl->>Nx: tls.yml: BYO checks, or copy the CA from rustfs1 and sign a node certificate
    Ctrl->>N1: flush handlers: systemctl daemon-reload (unit changed)

    Note over Ctrl,Nx: 3. Service
    Ctrl->>N1: check the node certificate against ca.crt and the OS store, pick the probe CA
    Ctrl->>N1: compare the process with the files, the binary and the served certificate, decide
    Ctrl->>N1: rustfs tls inspect (before any start or restart)
    Ctrl->>N1: a cluster-wide change: refuse when a cluster host dropped out after preflight
    Ctrl->>N1: point the rustfs symlink at the versioned binary
    Ctrl->>N1: systemctl start --no-block
    Ctrl->>Nx: systemctl start --no-block (all inactive hosts in parallel)
    N1-->>Nx: internode RPC until read and lock quorum
    Ctrl->>N1: wait for a main PID, then GET /health/ready until 200 and ready
    Ctrl->>Nx: same wait, in parallel
    Ctrl->>N1: rolling restarts of changed running nodes (next section)
    Ctrl->>N1: enable the unit at boot
    Ctrl->>N1: GET /minio/health/cluster until 200 (write quorum)
    Ctrl->>Nx: same gate on every host
```

**Notes:**

- **Guards first, and read only.** `validate.yml` (variables and the play
  shape) and `preflight.yml` (the host and the running process) run before
  anything is touched and are tagged `always`. A host that fails one is left
  exactly as it was. The guards that compare hosts (one cluster
  configuration, first bootstrap, cluster-wide changes, IAM key change) read
  facts the other hosts set in the same run: `validate.yml` resets them
  first, so a host whose run stopped early (also a rescued failure) never
  passes on old values, and the role needs the default linear strategy. The
  TLS checks of BYO material that need `python3-cryptography` run in the TLS
  stage; a host that fails there has new files on disk but is not
  restarted. A host can also fail after preflight (a download, a package, a
  TLS check): before any start or restart, every host whose run changes a
  cluster-wide key (layout, RPC secret, root credentials, IAM keys) checks
  that every cluster host reached the service stage, and refuses otherwise,
  so the others never restart onto values the failed host does not have.
- **Probe trust follows the certificate.** RustFS trusts `ca.crt` and, with
  `rustfs_tls_trust_system_ca`, the OS store too; a `uri` probe with
  `ca_path` trusts that file only. The service stage checks the node
  certificate against each store RustFS uses
  (`community.crypto.certificate_complete_chain`), refuses one that neither
  signs, and lets the probes use `ca.crt` when it signs the certificate,
  else the OS store.
- **Install once per version.** When the versioned binary
  `rustfs-<version>-<libc>` exists and matches the digest file the role
  wrote when it installed it, nothing is downloaded and no temporary
  directory is created. Otherwise the zip is downloaded into a temporary
  directory inside `rustfs_bin_dir`, checked against a pinned or given
  SHA-256 (upstream publishes no signatures), the extracted binary must
  report `rustfs_version` when run as the service user, and only then is it
  installed with its digest file. The `rustfs` symlink is not switched here.
- **The symlink moves with the restart.** `service.yml` points the `rustfs`
  symlink at the new binary right before a node starts or restarts (for a
  rolling restart inside `restart_node.yml`, per node). A rollout that stops
  at the first node leaves the other nodes on their old binary, also for a
  crash restart or a reboot before the next run.
- **Two env files.** The non-secret `rustfs_env_file` is diff-able and
  backed up; `secrets.env` (`root:root 0600`) holds the credentials. Both
  are rendered from the same dictionaries (`vars/main.yml`) that the restart
  decision compares with the running process. A start or restart loads the
  files on disk, so the service stage refuses to restart when they differ
  from the variables (a `--tags service` run after a change).
- **Parallel, non-blocking start.** RustFS reports `READY=1` to systemd only
  after it has read and lock quorum, so the first node of a cold cluster
  cannot finish starting before its peers run. All inactive nodes are
  started with `--no-block` in the same task; the role then waits for each
  node's own `/health/ready`, and finally for write quorum. The unit has
  `TimeoutStartSec=infinity`, so a node that waits for its peers is never
  killed by systemd.
- **Check mode** on a converged host changes nothing, skips every wait and
  reports pending restarts (for example after a `--tags config` run). It is
  not supported for a first install.

---

## Restart decision and rolling restart

There is no `restart rustfs` handler. A notified handler is lost when a run
dies between rendering a file and the flush, and it cannot choose between
restarting one node at a time and restarting all changed nodes together.
Instead, every run compares each node's running process (read by
`preflight.yml`, before anything changed) with the desired state:

- **Binary:** the file of `/proc/<MainPID>/exe` must be the versioned binary
  of `rustfs_version`: the same device and inode, because the kernel reports
  the canonical path and a symlinked `rustfs_bin_dir` would never match as a
  string.
- **Environment:** `/proc/<MainPID>/environ` (the environment systemd built
  from both env files when the process started) must hold every desired key
  with the desired value. The desired environment is the non-secret and the
  secret dictionary plus two non-secret markers in the env file:
  `ANSIBLE_RUSTFS_MANAGED_KEYS` (the sorted key names, so a removed key is a
  change) and `ANSIBLE_RUSTFS_UNIT_SHA256` (the digest of the unit file, so a
  unit change reaches the process).
- **Certificate:** with TLS on, a running node without another change must
  serve the certificate of `rustfs_cert.pem` (serial and expiry). RustFS
  hot-reloads replaced files but rejects a certificate that drops a name of
  the served one, and keeps the old one; the role waits one reload interval,
  then counts `tls` as a change.

The environment is read as root in a `no_log` task and never stored as a
fact; the decision keeps key names only. Because the decision is stateless,
a restart that an earlier run rendered but never performed (a
`--tags config` run, a run that died half way) happens on the next run, exactly
once, with the right mode. A start or restart loads the files and the
binary on disk, so a run in which they do not match the variables (the
config or install stage did not run) refuses instead of restarting without
converging.

| State of a node | What the role does |
|---|---|
| Not running (first bootstrap, stopped, crashed) | starts it, in parallel with the others |
| Running, same binary and environment, serves the certificate on disk | nothing |
| Running and changed: an env key or a secret (other than the two of the next row), the unit, or `rustfs_version` | rolling restart |
| Running and changed `RUSTFS_VOLUMES` (with `rustfs_allow_volumes_change`) or `RUSTFS_RPC_SECRET` | restarts the changed nodes together: old and new cannot coexist |
| Running and changed, `rustfs_rolling_restart: false` | restarts the changed nodes together |
| Still starting (not yet serving) and changed | restarts it together with the others |
| A certificate replaced that keeps every served name | nothing: RustFS reloads it |
| A certificate replaced that drops a name (reload rejected) | rolling restart (`tls`) |
| The files on disk differ from the variables (`--tags service` after a change) | refuses, nothing restarts |

The rolling restart runs inside one play: an included task file
(`restart_node.yml`) with `run_once` and a loop over the changed nodes in
play order, so restart, wait and peer checks stay together per node. Every
task delegates to the node being restarted.

```mermaid
sequenceDiagram
    participant Ctrl as Controller (run_once host)
    participant N as Node being restarted
    participant P as Its peers

    loop every node that needs a rolling restart, in play order
        Ctrl->>N: GET /health/ready of every peer, from N
        alt a peer is not ready
            Ctrl-->>Ctrl: fail: refusing to restart N (nothing restarted)
        end
        Ctrl->>P: poll /health/ready until no peer lists an unavailable or missing drive
        alt a drive stays offline
            Ctrl-->>Ctrl: fail: refusing to restart N (nothing restarted)
        end
        Ctrl->>P: stat DRIVE/.rustfs.sys/healing.bin on every other cluster host until gone
        alt a drive stays healing, or a host cannot be checked
            Ctrl-->>Ctrl: fail: refusing to restart N (nothing restarted)
        end
        Ctrl->>N: point the rustfs symlink at the versioned binary
        Ctrl->>N: systemctl restart --no-block
        Ctrl->>N: wait for a new MainPID, then /health/ready 200 and ready
        Ctrl->>P: poll /health/ready until no peer lists an unavailable or missing drive
    end
```

**Notes:**

- **Peers first.** A node goes down only when every peer is ready. A bad
  change or a dead peer therefore stops the rollout at one node at most.
  There is no skip list for a permanently dead peer: run with
  `rustfs_rolling_restart: false` in a maintenance window instead.
- **Every drive online before a node goes down.** `/health/ready` follows
  the read quorum of the present state only; it does not say whether the
  cluster survives losing the restarting node's drives as well, and RustFS
  has no maintenance probe. With one drive already offline, a restart can
  take an erasure set below read or write quorum (four nodes with four
  drives each: one set of 16 with parity 4, so one dead drive plus four
  restarting is five missing shards). The role does not compute which
  layouts survive: a node goes down only when every peer lists no
  unavailable or missing drive (`details.storage`; a node always lists its
  own missing drives, so an offline drive on any other node is seen). The
  node being restarted is not asked: restarting it costs nothing beyond its
  own drives, which is how a node with a dead drive is recovered. It waits up to
  `rustfs_ready_retries` x `rustfs_ready_delay` for that, because a peer can
  still list the drives of a node that started moments ago, and then
  refuses. A cluster with a dead drive is rolled after the drive is replaced
  and healed ([TROUBLESHOOTING.md](TROUBLESHOOTING.md#a-drive-is-offline)),
  or with `rustfs_rolling_restart: false` in a maintenance window.
- **No drive healing elsewhere.** A replaced (or returning) drive leaves the
  drive lists once RustFS has formatted it, but the erasure-set heal that
  rebuilds its shards can run for hours, and readiness does not report it.
  Until it ends, objects not rebuilt yet have one shard fewer, so the same
  quorum argument applies. RustFS keeps `<drive>/.rustfs.sys/healing.bin` on
  a drive while it heals it (`HEALING_MARKER_PATH`). Before each restart the
  role stats that marker at every drive root of `rustfs_volumes` on every
  other cluster host, delegated, so hosts outside `--limit` are checked too;
  it waits like the drive gate and refuses on a marker that stays or a host
  it cannot check. The node being restarted is not checked, for the same
  reason as above. RustFS writes the marker right after it has formatted the
  drive, before it rebuilds anything; in a test with 78 MB on the drive the
  marker appeared in the same 0.2 s poll in which the drive left the lists,
  and stayed for the 3 s of the rebuild.
- **Re-admission, not just readiness.** A node's own `/health/ready` says it
  can reach the cluster, not that the cluster reaches it again. The next
  node goes down only after every peer lists every drive online again (drive
  keys `poolIndex/setIndex/diskIndex` in the failure messages).
- **One rollout per play.** The loop covers the changed nodes of the whole
  play in play order, standalone nodes included, one at a time: a failure
  stops the rollout of every node after it, also of unrelated standalone
  nodes in the same play. Each node is probed and waited for with its own
  settings (probe CA, retries, delay, heal markers), which `service.yml`
  stores as facts.
- **`any_errors_fatal`.** A failure inside the `run_once` loop would
  otherwise fail only the `run_once` host while the other hosts carry on.
  The loop sits in a block with `any_errors_fatal: true`, so a failed
  rollout stops the play on every host. Re-running the play resumes it: the
  nodes that were restarted already match the desired state.
- **Why not `serial` or `throttle`.** `serial` breaks the first bootstrap
  (every node must start in the same run) and the consistency check, and it
  is refused. `throttle: 1` serialises each task separately, so the restart
  would run on every node before the first wait starts.
- **Timing.** In the four-node Molecule scenario a rolling restart takes
  about 10 s per node (restart, readiness, re-admission).

---

## Sandbox

The unit in `templates/rustfs.service.j2` starts from the upstream unit
(`deploy/build/rustfs.service`) and tightens it: `ProtectSystem=strict` with
`ReadWritePaths` templated from real paths (home, every data dir,
`rustfs_systemd_read_write_paths`), `ProtectHome`, `PrivateTmp`,
`PrivateDevices`, the `Protect*` kernel and clock directives,
`RestrictNamespaces`, `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
AF_NETLINK`, `LockPersonality`, `SystemCallArchitectures=native`, and empty
capability sets unless a listener port is below 1024. `SystemCallFilter` and
`MemoryDenyWriteExecute` are deliberately not used (unverified against the
io_uring read path and the allocator).

Results of the `default` scenario (one node, four tmpfs drives mounted at
the data dirs, so `rustfs_require_mounted_drives` keeps its default,
generated TLS, real start and S3 round trip), observed on Debian 12 under
Docker Desktop (arm64); the verify asserts behind every row also pass on
Debian 13 and Ubuntu 24.04:

| Question | Result |
|---|---|
| Does the unit start and serve unchanged? | Yes. No path was added and no directive was dropped. `systemd-analyze verify` reports nothing, `systemd-analyze security rustfs` rates the unit 3.1 ("OK"). |
| Does RustFS write outside the listed paths? | No. The only paths owned by the service user are the home and the data dirs; RustFS keeps its metadata in `<data dir>/.rustfs.sys`. The journal shows no permission or read-only error. |
| Does RustFS serve data from directories on the container's overlay root filesystem? | Yes, with `rustfs_unsupported_fs_policy: "warn"` (the `upgrade` scenario uses plain directories; the others need it while a tmpfs drive is unmounted, because the directory below sits on overlayfs): it logs `Unsupported filesystem type detected ... (overlayfs)` at WARN and continues. tmpfs is a supported filesystem. Production keeps the default `fail`; there the directory below an unmounted drive is on the root filesystem (XFS or ext4), which passes the check. |
| Does RustFS change the owner or mode of its drive roots at startup? | No. The drive roots stay `rustfs:rustfs 0750`, and the idempotence step is green. |
| What happens when a drive is not mounted? | The unit (ordered after the mounts, not bound to them) starts; RustFS reports the drive in `missingDrives`, serves on the other three and writes nothing to the empty `root:root 0755` directory below the mount point. A new tmpfs mounted later is not visible to the running process; after a restart and a role run (which sets the owner) RustFS formats and heals it without another restart. |
| And with two drives not mounted? | The node does not start: both directories sit on the root filesystem, and the distinct-disk check (on, as in production; each tmpfs has its own device number) exits with `local erasure endpoints must use distinct physical disks`, every 10 s. Two new tmpfs drives are taken in like one (four drives, parity 2). |
| Does boot wait for the unit? | No. With `DefaultDependencies=no` (the service defaults restored explicitly) `multi-user.target` is not ordered after `rustfs.service`. |
| Does systemd change secret values on their way from `secrets.env` into the process? | No. The test secret `molecule-secret $#'key-0123456789` (a space, `$`, `#` and `'`) reaches `/proc/<pid>/environ` byte for byte, S3 SigV4 requests authenticate with it, and the restart decision sees no difference on the next run. Inside a double-quoted `EnvironmentFile` value systemd only interprets `"`, `\` and line breaks, which validation already refuses. |
| Does the extra file `ca.key` in the TLS directory disturb RustFS? | No. RustFS scans only sub-directories of the TLS path for per-domain material and ignores plain files; `rustfs tls inspect` reports `single-cert/default`. |

The `distributed` scenario (four nodes with two tmpfs drives each,
internode TLS with one generated CA) runs the same unit unchanged: every node
starts, serves S3 through any node, and passes `systemd-analyze verify`;
internode RPC over HTTPS needs no extra path, address family or capability.
