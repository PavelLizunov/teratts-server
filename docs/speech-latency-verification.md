# Speech latency verification

Date: 2026-09-09. Branch: `agent/speech-latency-gpu`; original CPU base `ebdbe89`.

## Final admission decision

**GPU primary admission rejected after production verification.** The paired candidate run improved first play (1,991 → 1,292 ms), but the final production GUI first-play measurement was **2,366 ms**. GPU journal showed approximately 213 ms synthesis and no local CPU fallback; the complete delivery path did not demonstrate a stable improvement. Do not select only the favorable pair as acceptance evidence. No additional repeated campaign was run to search for a favorable result.

The task-owned primary drop-in was disabled, and the reviewed `235354c` entry release returned to **CPU-only**. GPU service/runtime/tunnel configuration is retained as a prepared candidate, not an active primary. Host retries remain zero. The original intermittent long-delay symptom is **not proven eliminated**. Improving the existing indirect network path is a remaining prerequisite to a defensible GPU-primary rollout, not authorization here to alter VPN/firewall topology.

## Implemented and exercised configuration

- CPU entry/fallback runs routing release `235354cef26ab9b79c76d3b0eb4b44e62ba1fca7`. Existing authenticated public endpoint is unchanged.
- Separate GPU service runs CUDA/warmup release `2bb1b32cc44c32279f4d5a8cd392e609b9c26248`, ONNX Runtime 1.27.0 **CUDA12** distribution, CUDA12.8 libraries and cuDNN9. No driver/global CUDA changes.
- GPU performs one complete short Russian inference per engine before binding its listener. Observed warmup 40.077 seconds plus approximately 11 seconds graph/normalizer loading; health unavailable before warmup, verified ready afterward. Service startup readiness is externally supervised (120-second health wait, 130-second systemd startup limit). This does not interrupt native inference cooperatively or warm every future tensor shape.
- GPU primary uses an encrypted, pinned-host-key SSH tunnel to loopback, a dedicated restricted forwarding identity on the GPU and a separate upstream bearer. The jump hop uses existing Tailscale SSH authorization, not OpenSSH authorized-key restrictions. SSH compression enabled only on this tunnel; no new public/LAN HTTP listener.
- Routed requests have one GPU attempt (3 seconds including full body) and at most one local CPU fallback within a shared 55-second queue-inclusive deadline. Five-second reserve skips GPU if insufficient budget. No guaranteed successful CPU completion under arbitrary load. CPU-only default remains 120 seconds.
- Host setting `maxRetries=0` applied through supported live settings, avoiding nested retries. No DSH restart, client-plugin replacement, driver change, model replacement or pronunciation change.
- User authorized Qwen unload to free VRAM. Its service was stopped; model/config/autostart settings retained. Tera GPU service and private tunnel were temporarily enabled, then stopped and disabled after primary admission was rejected. Their configuration is retained. A future GPU start requires at least 4,096 MiB free VRAM; concurrent Qwen/Tera GPU operation was not tested.
- Tera-only production activation used existing immutable-release/hash/health/rollback tooling. Previous CPU release retained. Temporary mock/candidate services stopped and temporary HTTPS candidate path removed.

## Measured latency and memory

These are short individual observations, **not** throughput/soak results, percentiles, or statistically established speedups.

| Comparison | CPU | GPU | Meaning |
|---|---:|---:|---|
| Same GPU-host CPU/CUDA sample 1 | 188 ms | 40,679 ms cold | Identified startup cost, not steady-state speed |
| Same-host sample 2 | 819 ms | 312 ms warm | Inference plus local request path |
| Same-host sample 3 | 453 ms | 166 ms warm | Inference plus local request path |
| Actual CPU entry / uncompressed GPU tunnel, sample 2 | 1,087 ms | 1,458 ms | Network erased GPU advantage |
| Actual CPU entry / uncompressed GPU tunnel, sample 3 | 595 ms | 1,223 ms | Network erased GPU advantage |
| Compressed tunnel, sample 2 | previous 1,087 ms | 899 ms | Subsequent single observation, not concurrent control |
| Compressed tunnel, sample 3 | previous 595 ms | 628 ms | No useful demonstrated gain for this text |
| Same GUI speech button, matched CPU then GPU candidate | 1,991 ms | 1,292 ms | First HTML audio play invocation; approximately 35% shorter in this pair |

Tailscale reported DERP relay (47 ms probe), not a direct connection. Compression improved observed WAV transport; no VPN/firewall modifications attempted. GUI first-play timestamp is a browser playback boundary, not microphone-measured audible latency. Final production GUI first-play was 2,366 ms; that contradictory measurement triggered primary rejection as documented above.

GPU observed memory: initial free 993 MiB prevented admission. After authorized Qwen unload, free 15,843 MiB / used 10 MiB. Comparison peak used 1,032 MiB; service after additional shapes used 1,064 MiB / free 14,789 MiB. Configured 512 MiB arena per session is not a total VRAM quota. cuDNN emitted unsupported-plan messages during warmup, but full inference completed and subsequent outputs passed checks; exact internal plan/JIT mechanism was not established.

## Audio and Russian-mode checks

Three matched CPU/GPU WAVs had exactly matching frame and byte counts, 44.1 kHz mono signed 16-bit PCM, nonzero samples and no clipping. Durations: 2.008 / 10.360 / 6.497 seconds. CPU/GPU waveform SNR: 49.53 / 45.25 / 46.12 dB. This is numerical parity evidence, **not subjective listening approval**. Pinned voice, model, converter, dictionary and approved lexicon retained. GPU uses a copied lexicon snapshot: future approvals must synchronize and verify that snapshot before expecting identical pronunciation across backends; automatic cross-host lexicon synchronization is not implemented.

## Failover and cancellation evidence

1. Real production-binary candidate, actual GPU available: HTTP200, backend `primary`, `russian_only`, 177,146 WAV bytes, 465 ms.
2. Stop only its tunnel, same request: HTTP200, backend `cpu`, same mode/bytes, 263 ms. Tunnel restored in `finally`.
3. Full browser → installed Host → Tailscale Serve → real engine-backed routing candidate with delayed loopback mock: positive control made one upstream attempt, one CPU synthesis, returned after 3,263 ms.
4. Click actual GUI Stop after the mock observed the next request. Wait 4.5 seconds beyond Stop: exactly one upstream attempt, zero audio play calls, zero active speech buttons. Candidate journal contained only the positive control's one CPU inference (encoder through vocoder); no CPU stages for cancelled request. Admission active/waiting returned to zero. This verifies this installed chain's tested cancellation path, not every HTTP/proxy variant or immediate interruption of native GPU work.
5. Stable production after activation returned HTTP200, backend `primary`, `russian_only`, 177,146 bytes, 670 ms. Original endpoint restored throughout non-test periods; temporary HTTPS route removed.

## Source verification and independent review

At routing snapshot `235354c`:

```sh
cargo test --offline --locked
cargo test --offline --locked --features cuda tera::tests::cuda
cargo clippy --offline --locked --bin teratts-server -- -D warnings
git diff --check
```

Lead actually executed: **119 passed / four resource-dependent ignored**, two CUDA warmup tests passed, production Clippy and whitespace checks passed. Warmup worker additionally ran full default/CUDA suites before routing integration (104/106 passed, four ignored). Independent final reviewer executed nine remote-primary tests and 18 server tests (one ignored), inspected actual final files and found no blocking source/security defect. Real TCP/Axum disconnect test is not merely a future-drop test, but uses a model-free surrogate with shared production helpers; live engine-backed full-chain test above supplies separate integration evidence.

Security review covered literal-loopback URL parsing before normalization, self-port rejection, separate sensitive authorization, disabled proxies/redirects/automatic retries, strict bounded WAV and mode validation, terminal 4xx/semantic 5xx, bounded safe 429 retry metadata, admission/deadline/cancellation ownership. No whole-system security assurance is claimed. Test-target Clippy still reports three pre-existing `unwrap` warnings in execution-provider tests; production Clippy passes.

## Client deadline candidate and remaining limits

Original GUI baseline was approximately 1.8 seconds, short RPCs 743/1,194/624 ms. A smaller first chunk (120 rather than 240 chars) regressed in one trial and was reverted. Existing 240-character split retained.

Repository client change adds a 65-second per-RPC wait, Stop/deadline child abort and late-response exclusion, with 58 JavaScript tests passing and independent playback/deadline review. Isolated browser substitution began playback in 1,787 ms. **This helper is not installed into the newer runtime-specific local GUI plugin**: wholesale replacement would remove compatibility changes. Do not claim lost-RPC watchdog deployment. The live speed improvement comes from server routing, GPU warmup and tunnel transport; one paired first-play improvement does not prove the original intermittent long-delay symptom eliminated under every condition.

## Operational rollback

Remove only the task-owned GPU-primary service drop-in, reload systemd and restart Tera to keep the current code CPU-only; alternatively use the existing rollback helper with exact previous CPU SHA `ebdbe89d9ee4acc063aebf699c695d8c2853887f`. Restore Host retries only deliberately; zero avoids retry amplification. No DSH restart is required. GPU service/tunnel can be stopped independently; routing then falls back within its bounded policy. Do not restore Qwen while assuming the former free-memory measurements still apply.
