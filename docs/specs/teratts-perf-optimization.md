# TeraTTS latency optimization — research (swarm, 2026-08-22)

Baseline (4 vCPU LXC, ORT 1.27 CPU, intra=4/inter=1): text-encoder ~36ms,
duration ~39ms, sampler (8-step diffusion) ~1.1s, vocoder ~1.7s per phrase;
long paragraph (371 frames, 24 vocoder chunks) ~9–10s. Models pinned; quality
must stay near reference. Ranked by value/risk.

## A. Zero-risk, near-free (do first; combined ~1.3–1.5×)

| # | Change | Speedup | Effort | Risk |
|---|--------|---------|--------|------|
| A1 | `GraphOptimizationLevel::All` on all 4 sessions (+ save optimized model) | 5–20% | 2 lines | none |
| A2 | `ExecutionMode::Sequential` + `memory_pattern(true)` | 5–15% sampler/vocoder | 2 lines | none |
| A3 | `mimalloc` global allocator | 3–8%, p99 −10–20% | 2 lines | none |
| A4 | Host `governor=performance`; systemd `CPUAffinity`, `Nice=-5` | 5–20% | host cmd | none |
| A5 | Transparent hugepages = always (host) | 2–5% | host cmd | none |
| A6 | IO-binding for sampler/vocoder loops | 5–12% | medium | none (validate) |

## B. Parallelism + streaming (big perceived win; medium effort)

| # | Change | Speedup | Effort | Risk |
|---|--------|---------|--------|------|
| B1 | Bounded parallel chunk synthesis (session pool + semaphore; intra_op×slots ≤ cores) | 2.5–3.5× wall on long text (9–10s→3–4s) | medium | none if chunks independent |
| B2 | Streaming WAV (channel + ordered dispatch) → TTFA ~0.5s | perceived huge | med-high | WAV header/streaming quirks |
| B3 | Chunk-boundary overlap-add crossfade (5–10ms) | quality enabler for B1 | low-med | HIGH without it |
| B4 | Thread config sweep (intra 4/sem1, 2/2, 1/4) | pick sweet spot | low | none |

## C. INT8 quantization (phased; offline Python, ort loads transparently)

| # | Change | Speedup | Effort | Risk |
|---|--------|---------|--------|------|
| C1 | Static INT8 text_encoder + duration_predictor (QDQ, per-channel, 50–100 calib) | 1.5–2× those (~−30ms) | low | very low |
| C2 | Static INT8 sampler (timestep-aware calib, keep emb/projection FP32) | 1.3–1.6× (−250–400ms) | medium | medium |
| C3 | INT8 vocoder (exclude ConvTranspose, final tanh FP32) | 1.2–1.4× | high | med-high; optional |

Projection: conservative(C1) ~1–3%; moderate(C1+C2) ~10–15%; aggressive(+C3) ~20–25%.

## D. Algorithmic (training-free)

| # | Change | Speedup | Effort | Risk |
|---|--------|---------|--------|------|
| D1 | Transformer Layer Caching on sampler | 1.5–2× sampler | medium | very low (threshold 0.03–0.05) |
| D2 | TeaCache timestep-output cache | 1.2–1.5× batch/repeated | low | low |
| D3 | DPM-Solver++ 6–7 steps / CFG 2.5 | 1.3–1.4× sampler | low | moderate; A/B required |
| D4 | Latent warm-start between chunks | 1.1–1.2× + coherence | low | low-med |

## E. Build-level

| # | Change | Speedup | Effort | Risk |
|---|--------|---------|--------|------|
| E1 | Native AVX2/FMA ORT build (+mimalloc, minimal_build) | 10–25% | high (source build) | very low |

## Recommended order
1. A1–A5 (free) → validate parity + bench.
2. B1+B3 (parallel + crossfade), then B2 streaming → TTFA win.
3. C1 (safe INT8) → C2 (sampler) behind flag, A/B listen.
4. D1 if more sampler headroom needed; E1 last.

All changes keep FP32 fallback behind env flags (`TERATTS_STREAM`,
`TERATTS_PARALLEL_CHUNKS`, `TERATTS_INT8`) so any regression is a one-line revert.

## Measured on the LXC (4-sentence paragraph, ru_f1)

- BEFORE (sequential, intra=4): **3.65s**.
- parallel=2 with intra=4: **4.5s** — SLOWER (8 ORT threads on 4 vCPU = oversubscription).
- parallel=2 with intra=2 (`TERATTS_ORT_THREADS=2`): **2.3–2.5s** (~1.5× faster). ✔ deployed
- Lesson: keep `intra_op × parallel_slots ≈ vCPU count`.
- Phase A (graph opts + mimalloc) is on by default; it changes numerics slightly
  (WAV bytes differ, same length) — listen-verify before treating as identical.
- INT8 (C1) not yet enabled: generate `.int8.onnx` via `tools/quantize_int8.py`,
  validate mel-MSE <1%, then set `TERATTS_INT8=1`.
