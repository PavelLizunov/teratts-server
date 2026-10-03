# Upstream and technology review — observed 2026-10-02/03 UTC

Primary sources fetched during this audit; no installation, runtime replacement, model download or benchmark. General search service returned HTTP 402, so discovery used known upstream endpoints and is representative, not an exhaustive market survey. Registry observations/versions/dates are saved in [upstream-versions.json](<upstream-versions.json>).

## Priority and compatibility

1. **Security patch before speculative speed work:** locked rustls 0.23.43 matches [RUSTSEC-2026-0285](https://rustsec.org/advisories/RUSTSEC-2026-0285.html), patched >=0.23.45. [Published patch registry record](https://crates.io/api/v1/crates/rustls/0.23.45) confirms availability. Keep reqwest 0.12 line if compatible; a transitive lock patch can be smaller than major migration. Must review lock diff and test on a permitted worker. No active runtime binary inspection performed.
2. **Low-risk candidates, not automatic updates:** flate2 1.1.9→1.1.10, tokenizers 0.23.1→0.23.2. Tokenizer changes still need golden ids/offsets/stress parity. No claim that latest means faster or safer; review upstream patch notes separately in an implementation task.
3. **Breaking-line optional changes:** reqwest 0.12.28→0.13.5, sha2 0.10.9→0.11.0, toml 0.9.12→1.1.6. Avoid blanket upgrades. Current HTTP/body/cancel/checksum/lexicon contracts must stay intact. Exact crate sources: [reqwest](https://crates.io/api/v1/crates/reqwest), [sha2](https://crates.io/api/v1/crates/sha2), [toml](https://crates.io/api/v1/crates/toml).
4. **Maintenance informational:** [paste no longer maintained](https://rustsec.org/advisories/RUSTSEC-2024-0436.html) through tokenizers; not a vulnerability finding. Prefer an upstream tokenizers decision instead of replacing transitive macro internals locally.
5. **Rust:** upstream [1.99.0](https://github.com/rust-lang/rust/releases/tag/1.99.0) is newer than discovered 1.98 installed toolchain. No compiler upgrade needed merely for this audit; benchmark/native-build results remain hardware and compiler dependent. Do not run a control-plane release build to compare them.

## Runtime and same-model options

| Option | Fresh source | Fit and practical constraint | Recommendation |
|---|---|---|---|
| ONNX Runtime 1.30.0 | [Release](https://github.com/microsoft/onnxruntime/releases/tag/v1.30.0), [API](https://api.github.com/repos/microsoft/onnxruntime/releases/latest) | Deployment artifact is 1.27/API27, ort remains rc13. Notes include CPU LayerNorm/RMSNorm/threading improvements; effect on these graphs unmeasured. Artifact ABI/glibc/CPU/provider checks required, old runtime retained. | First bounded runtime A/B candidate after correctness/security work, not wholesale source upgrade. |
| ort 2.0.0-rc.13 | [Release](https://github.com/pykeio/ort/releases/tag/v2.0.0-rc.13), [docs](https://docs.rs/ort/latest/ort/) | Already pinned; docs target newer runtime but API27 feature is intentional. Latest wrapper does not imply deployed dylib changed. | Keep version/API pin; separately validate dynamic runtime compatibility. |
| TeraTTSv2 | [Model metadata](https://huggingface.co/api/models/TeraSpace/TeraTTSv2), [model card](https://huggingface.co/TeraSpace/TeraTTSv2/raw/main/README.md) | Current upstream SHA equals repo pin f05ea799...; no newer model revision found. Alternate sampler1/2/4/8/16/32 and generator streaming are already upstream options. Model card lacks clear model-weight redistribution license. | Keep sampler8 as default; propose a sampler4 quality pilot only with fixed voices/RU pronunciation and human listening gate. Keep redistribution restriction. |
| Thread spin/pools/NUMA | [ORT threading](https://onnxruntime.ai/docs/performance/tune-performance/threading.html) | Current code already exposes spinning; 1.27 may not support every latest option. Session pool × RUAccent sessions × intra threads can increase oversubscription/RSS. | Hold fixed CPU quota/memory and compare TTFA/full response/CPU seconds/RSS, not raw latency alone. |
| GPU I/O binding | [ORT I/O Binding](https://onnxruntime.ai/docs/performance/tune-performance/iobinding.html) | Current graph chain copies tensors to host Vec then creates fresh inputs. Binding could retain device buffers, but dynamic shapes/provider/Rust lifetimes complicate it; CPU benefit unproven. | Profile device/host copy costs first. One narrow graph-boundary experiment if measurable; no generic tensor framework. |
| Actual streaming transport | [Tera card streaming](https://huggingface.co/TeraSpace/TeraTTSv2/raw/main/README.md) | HTTP currently buffers a full WAV for each text fragment; browser progressive chunks are not server sample streaming. Cancellation, timeline/format framing, authentication and proxy buffering change. | Separate protocol task only if first audible latency remains bottleneck; do not rename full-body RTF as TTFA. |
| INT8 | Current quantizer plus [ORT quantization docs](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html) | Current fallback random calibration is not representative; sampler/vocoder sensitive. FP32 is safe default. | Use representative pinned voice tensors/masks/text, graph validity and perceptual reference before any promotion. |

No measured benefit is claimed for these options. Old 3.65→2.3–2.5 s and GPU 1.33→0.705 s records describe prior hardware/configuration, not performance on the current deployment.

## Alternative engines/models, not drop-in upgrades

- **Piper 1.8.0:** [release](https://github.com/OHF-Voice/piper1-gpl/releases/tag/v1.8.0), [project](https://github.com/OHF-Voice/piper1-gpl), [Russian voices and license cautions](https://raw.githubusercontent.com/OHF-Voice/piper1-gpl/main/docs/VOICES.md). Reasonable CPU fallback candidate with existing C/C++/Python APIs; different pronunciation/voice quality and GPL engine/per-voice restrictions. Measure on actual deployment hardware with human speech-quality gates before comparing to Tera.
- **Qwen3-TTS 0.6B/1.7B:** [official README](https://raw.githubusercontent.com/QwenLM/Qwen3-TTS/main/README.md). Official Russian support, streaming and voice control; upstream advertises low first-packet latency, not a measured local result. GPU/memory/software requirements and contention with active models matter. A Python/GPU deployment would be larger change than ORT tuning. No matching GitHub release endpoint was found (404), so no invented latest version tag. Keep as quality/streaming exploration only.
- **Kokoro-82M:** [model card](https://huggingface.co/hexgrad/Kokoro-82M/raw/main/README.md), [metadata](https://huggingface.co/api/models/hexgrad/Kokoro-82M). Small permissively licensed model; official card describes 9 languages and does not establish Russian support. Not a Russian Tera replacement recommendation; at most separate English-only candidate.
- **Web Audio timeline scheduling:** [MDN AudioContext](https://developer.mozilla.org/en-US/docs/Web/API/AudioContext). Could reduce HTMLAudio segment transition gaps; not immune to autoplay policy. Current fake-browser tests already cover stale play/seek/autoplay. Consider only after real measured underruns, with disposal and user-activation gates.

## DSH integration status

Current installed profile peers expose 0.2.0-rc.1 contracts and pass actual Registry/Client Gateway tests. Public [GitHub latest endpoint](https://api.github.com/repos/deepseek-ai/deepseek-harness/releases/latest) and npm client-ui-react latest returned 404. [Typert protocol latest dist-tag](https://registry.npmjs.org/@deepseek-ai%2Fdsh-typert-protocol/latest) returned older 0.1.0-rc.6 than installed peers; do not downgrade based on that tag. No authoritative newer DSH release was established. Verify configured channel/peer codecs before future upgrade; historical runtime notes are not current plugin activation evidence.

## Proposed short authorized experiment sequence

After fixing revision semantics and rustls advisory:

1. Freeze exact source/model/voice/lexicon/config, immutable representative holdout, evaluator and hardware. Record cold startup separately from warm foreground and concurrent speculation.
2. Compare only runtime 1.27 vs 1.30 first, same quota, spinning, intra threads and engine pool. Measure first audible latency, full response, p50/p95, CPU/audio second, peak RSS, underruns/cancel settlement and output quality.
3. If no useful gain, stop; otherwise repeat paired order with noise/MAD and independent human listening. No broad campaign needed for one decision.
4. Only then try sampler4, GPU binding or alternative CPU engine as separate attributable candidates. Streaming and voice-cloning changes require their own task boundaries.

This document proposes work; it does not authorize or execute those benchmarks.
