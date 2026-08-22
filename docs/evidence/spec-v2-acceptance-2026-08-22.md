# Spec v2 acceptance evidence — 2026-08-22

## Verified

- Repository source and active Linux release: `b5e0cb0301e4d1111cf4435c99ae50fba5eaf6bd`; binary SHA-256 `bb9219cca8084b4f40ef385f5f21cf2e2a81612e5599ccc3a7629c5fe48ad8d6`.
- macOS hermetic suite: 60 passed, 1 model-backed test ignored by default.
- Debian model-backed differential test: pinned Python-generated full RUAccent corpus passed 7/7 cases; full Debian test suite passed 61 tests with the model-backed test ignored in the ordinary run.
- Linux runtime: unprivileged Debian 12 LXC CT 221 `teratts` on `pve-ninitux3`, static LAN address `192.168.0.221`, 4 vCPU, 6 GiB RAM, Proxmox 1 GiB swap limit, 16 GiB local disk, onboot enabled.
- Exact-SHA release path: `/opt/teratts/releases/b5e0cb0301e4d1111cf4435c99ae50fba5eaf6bd`.
- Dynamic ONNX Runtime: official Microsoft 1.27.0, archive SHA-256 `547e40a48f1fe73e3f812d7c88a948612c23f896b91e4e2ee1e232d7b468246f`, dylib SHA-256 `4061866361d9a8d2872f5f419c5515ce35a830a0c5c77ce1723320ac0dbabfc7`; no ONNX Runtime dependency appears in `ldd`.
- Clean standalone model install: all 57 pinned files downloaded into a fresh root and verified; installed model tree is about 871 MiB and includes full RUAccent assets.
- Service: non-root `teratts.service`, exact app/model SHA in live `/health`, RUAccent `full`, loopback-only `127.0.0.1:8088`, mandatory bearer authentication, valid WAV smoke test, LAN-IP connection failure.
- Admission/resource contract: real four-request test admitted three `200` WAV responses and returned one immediate `429` with `Retry-After: 1`; predicted duration is rejected before latent allocation and checked/fallible allocations are used.
- Serial soak: 20 authenticated requests passed; RSS remained about 1.69 GiB, below the 5 GiB service high-water limit.
- Reboot recovery: CT 221 and enabled `teratts.service` returned to exact-SHA ready state after guest reboot in about 13 seconds.
- Rollback drill: `dfe18e2 -> d62a0fb -> dfe18e2` completed with exact-SHA health checks and final authenticated WAV acceptance; later releases retained the same immutable activation contract.
- DSH plugin source: `0.2.0` uses a Host Remote, host-side endpoint/credential, strict rc.8 codecs, DSH loading/stop primitives, one local `currentColor` speaker SVG, accessible error/loading state, global epoch-gated playback and cleanup. Five plugin tests pass.
- DSH profile package dependency was updated to local `dsh-client-ui-teratts` `0.2.0` without restarting the active DSH host; `TERATTS_TOKEN` is configured write-only in the DSH credential service.
- Cross-platform quality: Windows and Linux `cargo check --locked` passed; macOS and Linux full tests passed; strict `cargo clippy --all-targets -- -D warnings` passed on Rust/Clippy 1.96 and 1.98.
- Durable Trajectory remediation prompt is stored at `docs/trajectory-prevention-prompt.md`; external restart/browser steps are stored at `docs/evidence/dsh-browser-acceptance.md`.

## Not verified / pending

- CT 221 Tailnet re-enrollment on kernel TUN: the first userspace-mode login reached `machineAuthorized` but never received/persisted a netmap; CT remains unprivileged with only `/dev/net/tun` passed through and awaits one new authorization plus reboot-persistence proof.
- Tailnet-only HTTPS Serve for CT 221.
- Tailnet HTTPS bearer rejection and authenticated `/tts` from another Tailnet device.
- DSH host-side endpoint/credential switch from Windows fallback to CT 221.
- DSH `0.2.0` activation: the current DSH process has not been restarted, deliberately avoiding self-termination from an active DSH session.
- Real browser acceptance: DOM placement, click/loading/play/stop/replay, keyboard/focus/ARIA, Toast, console cleanliness and media cleanup.
- Windows Scheduled Task/Tailscale Serve retirement. Windows remains the rollback fallback until Linux browser acceptance passes.
- Client cancellation cannot interrupt an in-flight ONNX `Session::run`; it prevents later chunks/results but the current native call completes.

## Current human gate

Authorize the Tailnet device `teratts` using the URL emitted by `tailscale up`. After authorization, configure Tailscale Serve, verify HTTPS, switch DSH host settings/credential, restart DSH only through an external management channel, perform browser acceptance, then retire the Windows fallback.
