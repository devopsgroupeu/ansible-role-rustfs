# Architecture

This document describes how the role deploys RustFS and what the Molecule
scenarios proved about the systemd sandbox.

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

Results of the `default` scenario (one node, four drive directories,
generated TLS, real start and S3 round trip), observed on Debian 12 under
Docker Desktop (arm64); the verify asserts behind every row also pass on
Debian 13 and Ubuntu 24.04:

| Question | Result |
|---|---|
| Does the unit start and serve unchanged? | Yes. No path was added and no directive was dropped. `systemd-analyze verify` reports nothing, `systemd-analyze security rustfs` rates the unit 3.1 ("OK"). |
| Does RustFS write outside the listed paths? | No. The only paths owned by the service user are the home and the data dirs; RustFS keeps its metadata in `<data dir>/.rustfs.sys`. The journal shows no permission or read-only error. |
| Does RustFS serve data from directories on the container's overlay root filesystem? | Yes, with `rustfs_unsupported_fs_policy: "warn"`: it logs `Unsupported filesystem type detected ... (overlayfs)` at WARN and continues. The scenarios therefore use plain directories, not Docker volumes. Production keeps the default `fail`. |
| Does RustFS change the owner or mode of its drive roots at startup? | No. The drive roots stay `rustfs:rustfs 0750`, and the idempotence step is green. |
| Does systemd change secret values on their way from `secrets.env` into the process? | No. The test secret `molecule-secret $#'key-0123456789` (a space, `$`, `#` and `'`) reaches `/proc/<pid>/environ` byte for byte, S3 SigV4 requests authenticate with it, and the restart decision sees no difference on the next run. Inside a double-quoted `EnvironmentFile` value systemd only interprets `"`, `\` and line breaks, which validation already refuses. |
| Does the extra file `ca.key` in the TLS directory disturb RustFS? | No. RustFS scans only sub-directories of the TLS path for per-domain material and ignores plain files; `rustfs tls inspect` reports `single-cert/default`. |
