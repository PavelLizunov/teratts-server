# Linux deployment artifacts

Native Debian 12/systemd deployment for approved Spec v2. See [`docs/deployment/linux.md`](../../docs/deployment/linux.md).

```text
preflight.sh                 validate existing Debian 12 unprivileged LXC
install-host.sh              create non-login identity, directories, unit, helpers
install-model.sh REV DIR     publish pinned model revision immutably
install-release.sh SHA BIN   publish exact-SHA binary immutably
activate.sh SHA              atomic app switch, health gate, automatic restoration
verify-health.sh [SHA] [REV] structured loopback health check
acceptance.sh                listener, immutability, health, and WAV smoke checks
rollback.sh [SHA]            activate an earlier immutable release
systemd/teratts.service      loopback-only hardened service
```

Scripts contain no secrets and make no LXC, Tailscale, DSH, Git, or Rust-source changes. Run install/activation operations as root from an external management session.
