# Spec v2 acceptance evidence — 2026-08-22

## Verified

- Repository source and active Linux release: `49eb9c45b559e7b1884104fc85f2a382c3ab4699`; binary SHA-256 `bc20a61c0eea82d2f2f81e6bfdbc94b36e40c09b8594c92ee26d0d2556ebf4f8`.
- Perf release (2026-08-23): Phase A (ORT graph opts + mimalloc) + bounded parallel chunks
  (`TERATTS_PARALLEL_CHUNKS=2`, `TERATTS_ORT_THREADS=2`) → 4-sentence paragraph 3.65s → 1.6s
  (~2.3×). INT8 rejected (text_encoder 95% rel error under synthetic calibration). See
  `docs/specs/teratts-perf-optimization.md`.
- Speech-front (2026-08-23, release `b11b631`): vendored `speech-front` normalizer
  (`src/speechfront.rs` + `src/lexicon.toml`, chislo=0.3.1) as opt-in `TERATTS_SPEECH_FRONT=1`
  (enabled on the LXC). Expands versions/numbers/dates/percents/units + approved lexicon to
  natural Russian before TTS (e.g. «v0.8.0» → «вэ ноль восемь ноль», «15%» → «пятнадцать
  процентов»). Unknown tech identifiers (hex SHAs, CamelCase) are preserved per speech-front
  philosophy — add a drop/spell policy if they must not be spoken.
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

## Verified (browser acceptance, 0.6.x)

- DSH plugin `0.6.1` is live; the voice action renders and plays. User confirmed a
  clean Russian sentence sounds **excellent**, matching suflyor/horizon quality.
- Full server pipeline proven byte-identical to the known-good `suflyor-teratts`
  reference: the four core ONNX graphs, `ru_f1` `style_ttl`/`style_dp` embeddings,
  and `indexer/rng/chunk/num2words` plus sampler/vocoder math all match. Hence
  identical input yields identical audio.
- `russian_stress` defaults to **off** (suflyor parity); full RUAccent remains a
  settings toggle (`stress`). A/B showed the flag changes the waveform.
- Markdown-heavy input reads less naturally than clean prose; the read-aloud is
  optimized for prose. `cleanMarkdown` no longer injects English ("code block").
- Synthesis is CPU-bound on the 4-vCPU LXC: ~1.1s sampler + ~1.7s vocoder per
  short phrase; a 371-frame paragraph ≈ 9–10s. Matches the distilled 8-step
  diffusion cost; suflyor is faster only on faster hardware.

## Not verified / pending

- Tailnet edge is verified: the still-unprivileged CT uses `keyctl=1`, only `/dev/net/tun`, persistent profile/IP `100.112.26.106`, MagicDNS `teratts.tail9fd337.ts.net`, bidirectional direct peer ping and reboot persistence. A narrow OUTPUT reject for Tailscale control pool TCP/80 forces the client around a confirmed controlhttp upgrade hang onto TCP/443; Tailscale 1.102.2 is pinned pending upgrade acceptance.
- Tailnet-only HTTPS Serve is verified with a valid Let's Encrypt certificate; health works from DSH and macOS, unauthenticated synthesis returns `401`, and authenticated synthesis returns a valid WAV.
- DSH host-side endpoint is staged to `https://teratts.tail9fd337.ts.net`; credential `TERATTS_TOKEN` is configured.
- Windows Scheduled Task/Tailscale Serve retirement. Windows remains the rollback fallback until the user confirms the Linux voice action for regular use.
- Client cancellation cannot interrupt an in-flight ONNX `Session::run`; it prevents later chunks/results but the current native call completes.

## Current human gate

Restart DSH only through the verified external `mac-worker -> harness-test` SSH channel after ending the active DSH session, then perform the browser acceptance checklist. Retire the Windows fallback only after the Linux voice action passes that browser gate.
