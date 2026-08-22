# Linux deployment artifacts

Native Debian 12/systemd deployment for approved Spec v2. See [`docs/deployment/linux.md`](../../docs/deployment/linux.md).

```text
preflight.sh                         validate existing Debian 12 unprivileged LXC
build-release.sh SHA OUT             build with compile-time TERATTS_APP_GIT_SHA
install-host.sh                      create non-login identity, directories, unit, helpers
install-model.sh REV DIR             publish pinned model revision immutably
install-release.sh SHA BIN ORT_TGZ   verify and publish binary + pinned ORT dylib
activate.sh SHA                      verify both artifacts, switch, health gate, restore
verify-health.sh [SHA] [REV] structured loopback health check
acceptance.sh                listener, immutability, health, and WAV smoke checks
rollback.sh [SHA]            activate an earlier immutable release
ort-artifact.env                     official ORT 1.27 URL and SHA-256 pins
systemd/teratts.service              loopback-only hardened service
systemd/tailscale-control-443.service narrow control-port workaround
systemd/tailscaled-control-443.conf   tailscaled ordering drop-in
```

Scripts contain no secrets and make no LXC, Tailscale, DSH, Git, or Rust-source changes. Run install/activation operations as root from an external management session.

## Tailnet edge

The approved unprivileged LXC uses `features: keyctl=1,nesting=1` and only
`/dev/net/tun`. On this network, Tailscale control's TCP/80 upgrade connected
but hung instead of falling back to 443 (the class documented by Tailscale issue
#4544). Install the two `systemd/tailscale-*443*` files before enrollment; they
reject only `192.200.0.0/24:80`, forcing control traffic to TCP/443. Rollback
removes/disables these files and restarts `tailscaled`; unrelated HTTP egress is
untouched. Keep the verified Tailscale version pinned until an upgrade passes
map-poll, ACME, reboot and Serve acceptance.
