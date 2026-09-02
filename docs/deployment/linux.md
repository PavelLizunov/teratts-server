# Debian 12 LXC deployment

This runbook installs an already-built, exact-commit TeraTTS binary into an **existing unprivileged Debian 12 LXC**. It does not create or modify the LXC, build Rust, change Tailscale automatically, restart DSH, or embed credentials.

## Contract

- Runtime identity: system account `teratts`, home `/var/lib/teratts`, shell `/usr/sbin/nologin`.
- App releases: `/opt/teratts/releases/<40-character-git-sha>`; root-owned, non-writable. Each contains the binary, `release.env`, and `lib/libonnxruntime.so.1.27.0`.
- Active app: atomic `/opt/teratts/current` symlink. The service loads ORT only through absolute `ORT_DYLIB_PATH=/opt/teratts/current/lib/libonnxruntime.so.1.27.0` from that release's metadata.
- Models: `/var/lib/teratts/models/teratts-v2-f05ea799094571a3553904a555df3834fb0b963b`; root-owned, non-writable. The server appends this pinned directory name to `--model-dir`; there is intentionally no model `current` link.
- Listener: `127.0.0.1:8088` only. Tailnet HTTPS is provided separately by Tailscale Serve.
- Runtime settings: `/etc/teratts/teratts.env`, root-owned and group-readable by `teratts`; never commit its contents.

The deployment scripts require `/health` to report `status=ready`, exact `app_git_sha`, and the pinned model revision. Do not activate a binary whose health contract is older than approved Spec v2.

## Build artifact handoff

Build on an approved Linux worker from a clean checkout of the exact commit:

```sh
git checkout --detach <sha>
test "$(git rev-parse HEAD)" = <sha>
test -z "$(git status --porcelain)"
deploy/linux/build-release.sh <sha> /srv/staging/teratts-server
if ldd /srv/staging/teratts-server | grep -q onnxruntime; then
  echo 'unexpected ONNX Runtime ELF dependency' >&2
  exit 1
fi
```

`build-release.sh` runs `TERATTS_APP_GIT_SHA=<sha> cargo build --release --locked`, rejects a different `HEAD` or tracked changes, and prints the binary SHA-256. Transfer the binary and its recorded hash over an authenticated channel.

Also obtain the official Microsoft archive named in `deploy/linux/ort-artifact.env`. Independently verify the pinned archive SHA-256 `547e40a48f1fe73e3f812d7c88a948612c23f896b91e4e2ee1e232d7b468246f`; `install-release.sh` repeats this check, extracts only `libonnxruntime.so.1.27.0`, and verifies dylib SHA-256 `4061866361d9a8d2872f5f419c5515ce35a830a0c5c77ce1723320ac0dbabfc7`.

Prepare models with the application downloader in a staging location. The source directory passed to `install-model.sh` is the complete `teratts-v2-<revision>` directory and must include `manifest.json`. The installer rejects symlinks and writes a full `SHA256SUMS` inventory before publishing it immutably.

## Install

Run from an external SSH/Tailscale management session, not from an active DSH request:

```sh
sudo deploy/linux/preflight.sh
sudo deploy/linux/install-host.sh
sudo deploy/linux/install-model.sh \
  f05ea799094571a3553904a555df3834fb0b963b \
  /srv/staging/teratts-v2-f05ea799094571a3553904a555df3834fb0b963b
sudo deploy/linux/install-release.sh \
  <sha> \
  /srv/staging/teratts-server \
  /srv/staging/onnxruntime-linux-x64-1.27.0.tgz
```

Put non-secret tuning and any credentials outside Git:

```sh
sudoedit /etc/teratts/teratts.env
sudo chown root:teratts /etc/teratts/teratts.env
sudo chmod 0640 /etc/teratts/teratts.env
```

Do not put secrets in the unit, scripts, shell history, URLs, or checked-in files. If bearer authentication uses a file-based option in the approved runtime, provision it under `/etc/teratts/` as root:`teratts` mode `0640` and reference the path from `teratts.env`.

## Activate and verify

```sh
sudo deploy/linux/activate.sh <sha>
sudo deploy/linux/acceptance.sh
sudo systemd-analyze verify deploy/linux/systemd/teratts.service
sudo systemd-analyze security teratts.service   # advisory; review, do not chase a score blindly
```

Activation verifies the release binary hash, pinned ORT dylib hash/name/version/absolute path, and every installed model file before changing `current`. It then restarts **only `teratts.service`** and polls structured health. A missing or wrong dylib cannot switch the link; a post-switch load or health failure restores the old link and restarts the old exact-SHA release. Acceptance additionally re-hashes the active dylib, proves the service is enabled/active and port 8088 is loopback-only, and requires a bounded authenticated full-RUAccent `/tts` request to return a non-empty RIFF/WAVE file.

For reboot recovery, from the same external channel:

```sh
sudo reboot
# reconnect after boot
sudo /usr/local/libexec/teratts/acceptance.sh
```

## Tailscale Serve & Networking Architecture

After local acceptance, inspect existing Serve state before changing it:

```sh
sudo tailscale status
sudo tailscale serve status
```

Configure the container's Tailnet-only HTTPS root to proxy to loopback (current Tailscale CLI syntax):

```sh
sudo tailscale serve --bg http://127.0.0.1:8088
sudo tailscale serve status
curl --fail --silent --show-error https://<approved-tailnet-host>/health
```

Never bind TeraTTS to `0.0.0.0`, publish port 8088 to LAN/Internet, or place a private hostname in Git. If this node already serves another application, use an explicitly approved path/port mapping rather than overwriting it; capture `tailscale serve status` out-of-band first.

To remove only this node's Serve configuration after operator confirmation:

```sh
sudo tailscale serve reset
```

### Network Stability & Connection Dropout Analysis

1. **TLS Termination & Proxying**:
   - `tailscale serve` **terminates TLS** directly within the local `tailscaled` daemon on interface `tailscale0` (port 443) using automatic Let's Encrypt certificates.
   - Decrypted traffic is reverse-proxied over unencrypted HTTP/1.1 to `http://127.0.0.1:8088`.
   - Incoming client requests negotiate **HTTP/2** with `tailscaled`.

2. **HTTP/2 Multiplexing & Head-of-Line Stalls**:
   - Because HTTP/2 multiplexes multiple streams over a single persistent TCP connection, long-running TTS generation (where synthesis computes for several seconds before sending audio bytes) creates periods of TCP silence.
   - If the underlying WireGuard path drops, wanders between DERP relays, or gets stalled by stateful NAT timeouts, all multiplexed HTTP/2 streams to `https://teratts.tail9fd337.ts.net` hang together.
   - Clients must configure application-layer request timeouts (e.g. 120s) and TCP keepalive to detect dead connections early.

3. **MTU Mismatch & Path MTU (PMTU) Black Holes**:
   - The host/veth LAN MTU is typically 1500 bytes, whereas the Tailscale WireGuard overlay MTU is **1280 bytes**.
   - If intermediate network devices drop ICMP "Fragmentation Needed" messages (PMTU black hole), large HTTP responses (such as multi-megabyte synthesized WAV audio payloads) will stall and drop packets, while small `/health` requests succeed.
   - Ensure TCP MSS clamping is configured on upstream firewalls if WAN PMTUD is unreliable.

4. **TCP Keepalive & NAT Expiration**:
   - Default Linux `tcp_keepalive_time` is 7200 seconds (2 hours), whereas home/NAT firewalls often drop idle translation states after 30–60 seconds.
   - If direct peer-to-peer UDP WireGuard fails and traffic routes via a DERP relay, idle connections without keepalive will silently disconnect.
   - Tune sysctl keepalives in the container or host if drops persist:
     ```ini
     net.ipv4.tcp_keepalive_time = 60
     net.ipv4.tcp_keepalive_intvl = 10
     net.ipv4.tcp_keepalive_probes = 6
     ```

5. **Tailscale 443 Control Workaround (`tailscale-control-443.service`)**:
   - Installed to bypass Tailscale issue #4544, where Tailscale's HTTP port 80 control-upgrade probe hung on certain networks.
   - The rule issues `REJECT --reject-with tcp-reset` for `192.200.0.0/24:80`.
   - Note: This rule requires `CAP_NET_ADMIN` in the LXC container. It covers only the legacy 192.200.0.0/24 subnet; global DERP servers use broader IP ranges.

## Resource Constraints & Cgroup Assessment

In `deploy/linux/systemd/teratts.service`, cgroup v2 limits are strictly enforced:

- **`CPUQuota=400%` (CFS Bandwidth)**:
  - Allocates 400ms of CPU time per 100ms CFS quota window (4 CPU cores).
  - When `PARALLEL_CHUNKS=2` and `ORT_THREADS=2` run, compute load matches the 4-core allocation.
  - Exceeding 4 threads (e.g. 4 slots * 4 threads = 16 threads) will consume the 400ms quota in just 25ms, causing the kernel to **throttle and freeze the process for the remaining 75ms of every 100ms period**. This causes severe latency spikes and `/health` probe timeouts.
- **`MemoryHigh=5G` & `MemoryMax=5500M`**:
  - Baseline RSS at 2 slots is ~4.17 GiB (loaded ONNX models, RUAccent models, and indexer).
  - `MemoryHigh=5G` leaves ~830 MiB headroom before the kernel triggers synchronous direct reclaim, which degrades latency.
  - `MemoryMax=5500M` leaves only a 500 MiB buffer above `MemoryHigh`. Exceeding 5500M triggers an immediate kernel OOM kill (`SIGKILL`).
  - **Do NOT configure `PARALLEL_CHUNKS > 2`** on an LXC with 6 GiB RAM.
- **`TasksMax=512` & `LimitNOFILE=65536`**:
  - `TasksMax=512` bounds the total threads across Tokio's worker pool, Tokio's blocking pool, ONNX Runtime per-session intra-op threads (~28 per slot), and chunk workers.
  - `LimitNOFILE=65536` ensures socket and model file descriptor headroom.

## Health Monitoring, Observability & Recovery

1. **Failure Transparency in `verify-health.sh`**:
   - `verify-health.sh` polls `/health` up to 30 attempts (1s delay).
   - On non-200 responses (e.g. HTTP 503 during warmup or verification failure), the exact HTTP code and JSON body (including `verification`, `model_revision`, and `app_sha_verified`) are reported.
   - On connection failures (e.g. curl exit 7 connection refused), the curl error and systemd service state (`systemctl is-active`) are surfaced immediately.

2. **Systemd Watchdog & Recovery**:
   - `teratts.service` currently runs as `Type=simple`.
   - `WatchdogSec` is currently disabled because the application binary has not yet implemented `sd_notify("WATCHDOG=1")`.
   - If ONNX Runtime deadlocks or hangs inside a native C++ thread pool, `Type=simple` with `Restart=on-failure` will not restart the service because the process does not exit.
   - Roadmap: Integrate `sd_notify` in `src/server.rs` to report `READY=1` on startup and send periodic `WATCHDOG=1` pings from an independent liveness loop. Once compiled, configure `Type=notify` and `WatchdogSec=30s` in `teratts.service`.

## Rollback

List immutable candidates and choose the exact SHA; explicit rollback is reproducible:

```sh
ls -1 /opt/teratts/releases
sudo /usr/local/libexec/teratts/rollback.sh <previous-sha>
sudo /usr/local/libexec/teratts/acceptance.sh
```

Without an argument, `rollback.sh` selects the newest other release by directory modification time; prefer the explicit SHA in production records. Rollback never deletes or modifies releases/models. Garbage collection is a separate reviewed operation and is not automated.

## DSH safety rule

No artifact in this kit invokes, reloads, or restarts DSH. Do not restart DSH from any request/session served by that DSH process. Any later DSH integration change must use an external management channel and a fresh validation session.
