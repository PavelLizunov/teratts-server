# Spec v2: Linux-first TeraTTSv2 Server and DSH Voice

## 1. Intent & Invariants
- What: replace the experimental Windows runtime with a reproducible Linux service providing full pinned TeraTTSv2/RUAccent behavior and native DSH voice actions.
- Runtime: a new unprivileged Debian 12 LXC on `pve-ninitux3` local storage; 4 vCPU, 6 GiB RAM, 1 GiB swap, 16 GiB disk; `harness-test` remains control-plane only.
- Network: daemon binds only `127.0.0.1:8088`; Tailscale Serve is the Tailnet-only HTTPS edge; no LAN/Internet listener.
- Model: revision `f05ea799094571a3553904a555df3834fb0b963b`; distilled core plus all used `ruaccent/` assets; teacher sampler and `nn_accent/big.onnx` are excluded.
- RUAccent: `full` and Russian stress are defaults; manual `+` is authoritative; `dictionary` and `disabled` are startup modes.
- Safety: one active synthesis plus two waiting; overflow is `429`; queue TTL 60 s; request deadline 120 s; max text 2,000 chars; max predicted audio 180 s; every allocation is checked.
- Deployment: build exact committed SHA with `cargo build --release --locked`; immutable `/opt/teratts/releases/<sha>` and `/var/lib/teratts/models/<revision>`; atomic `current` switch and verified rollback.
- Process: architecture drift requires a Spec amendment; DSH restarts are forbidden from sessions served by that DSH process.

## 2. Interface / Data Contract
```rust
enum Language { Ru, En }
enum RuAccentMode { Full, Dictionary, Disabled }
struct TtsRequest { text: String, voice: Option<String>, language: Option<Language>, duration_scale: Option<f32>, russian_stress: Option<bool> }
struct HealthResponse { status: ReadyState, app_git_sha: String, model_revision: String, verification: Verification, ruaccent_mode: RuAccentMode, ruaccent_ready: bool, sample_rate: u32, voices: Vec<String>, queue: QueueView }
struct ApiError { code: String, message: String, retry_after_ms: Option<u64> }
// GET /health; POST /tts -> audio/wav; every failure -> JSON.
// CLI: --download-models, --verify-models, --serve, --speak.
// DSH browser -> assistantVoice Host Remote -> configured HTTPS endpoint.
// Endpoint and bearer credential live in Host settings/credentials, never in the client bundle.
```

## 3. Verification Checklist
- [ ] Manifest and immutable installer cover distilled core plus every used RUAccent asset with SHA-256; clean, corrupt and concurrent-install tests pass.
- [ ] Rust `full`, `dictionary`, `disabled`, manual `+`, homographs and `ё` match pinned Python reference fixtures.
- [ ] Tokenizer IDs/offsets/masks and all four RUAccent model decisions match reference fixtures; Russian and English synthesis pass.
- [ ] Duration/allocation bounds, deadline, bounded queue, cancellation generations and stale-result discard are tested.
- [ ] HTTP tests cover JSON errors, limits, language/voice/rate, busy, timeout, bearer auth and live readiness.
- [ ] DSH uses native loading/stop primitives and one local 16px `currentColor` speaker SVG; no emoji or private hostname in the client bundle.
- [ ] Real browser acceptance proves placement, click/loading/play/stop/replay, keyboard/focus/ARIA, errors, cleanup and clean console.
- [ ] Exact-SHA non-root systemd deployment, Tailnet-only HTTPS, restart/reboot recovery, bad-release rejection and rollback are proven.
- [ ] Windows Scheduled Task and Serve are removed only after Linux acceptance; evidence and remaining limitations are committed and pushed.
