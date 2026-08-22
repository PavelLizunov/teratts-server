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

## Tailscale Serve

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
