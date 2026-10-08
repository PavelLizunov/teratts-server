# Russian STT: broader evidence review, 2026-10-08

## Decision and scope

Test Qwen3-ASR-1.7B first, but do not declare it a universal winner or require the
speaker to dictate one sentence at a time. The approved personal pilot is five
fixed retained clips (74.620875 seconds total) plus two synthetic one-second
controls. The current Parakeet production route remains unchanged.

## Candidates and evidence quality

### Qwen3-ASR-1.7B / 0.6B

[Official source](https://github.com/QwenLM/Qwen3-ASR) explicitly supports Russian.
1.7B is the accuracy-first pilot; 0.6B is a possible later speed alternative, not
a silent substitution. Original 1.7B safetensors contain approximately 2.349B
parameters including the audio encoder, despite the short model family name.
Pinned pilot revision: `7278e1e70fe206f11671096ffdd38061171dd6e5`.

Existing native implementations avoid writing a new model engine:
[antirez/qwen-asr](https://github.com/antirez/qwen-asr) (CPU/BLAS, CUDA and ROCm)
and [speech.cpp](https://github.com/NairoDorian/speech.cpp) / transcribe.cpp
(Linux Vulkan). Different ports/precisions require their own parity tests; files
named GGUF are not universally interchangeable. This pilot uses original BF16
assets with the inspected C CPU engine, revision
`924694251d9e0f18e5d86bbd06aa3ab5f870002d`, not a community quantized GGUF.
Deck Vulkan latency is not measured by that pilot.

Community enthusiasm does not remove failure modes:
[noise/echo issue 165](https://github.com/QwenLM/Qwen3-ASR/issues/165) reports
nonempty interjections on some noise;
[mixed-length Transformers batch issue 207](https://github.com/QwenLM/Qwen3-ASR/issues/207)
reports corrupted short-item results; [streaming issue 148](https://github.com/QwenLM/Qwen3-ASR/issues/148)
reports streaming problems. These are reports, not confirmed reproductions in
our engine. Single-clip offline tests and negative controls avoid assuming that
all official/framework features work equivalently in native ports.

### GigaAM v3 Russian — distinct from rejected Multilingual trial

[Official evaluation](https://github.com/salute-developers/GigaAM/blob/main/evaluation.md)
reports Natural Speech WER 7.8% for CTC and 6.9% for RNNT, versus 13.4% for its
Whisper baseline. These are the model author's own measurements with their exact
corpora/settings, not a personal-voice or code-switch score.

[Open independent multi-domain results](https://github.com/vakovalskii/stt-ru-benchmark)
report GigaAM v3 6.95%, Whisper turbo 7.73%, Parakeet v3 9.27% on spontaneous
speech. That split has only 20 utterances, broad overlapping intervals, and the
author also operates a commercial gateway. The stronger audiobook split has
296 items. It is valuable because methods/raw outputs and domain limitations
are disclosed, not because these numbers predict our exact setup.

Do not confuse GigaAM v3 Russian RNNT/CTC with ai-sage GigaAM Multilingual
large_ctc. The latter was previously tried and rejected by the user; repeating
that same trial is not a new discovery. Russian v3 may deserve a separately
approved future comparison if Qwen fails, but technical English vocabulary
remains a concern. The Russian multi-domain study's Latin-word subset is tiny.

### Whisper stock and Russian fine-tunes

Stock large-v3/turbo has mature [whisper.cpp](https://github.com/ggml-org/whisper.cpp)
CPU/Vulkan support. It is not a newly released model.
[antony66 Russian large-v3](https://huggingface.co/antony66/whisper-large-v3-russian)
claims CV17 Russian WER 6.39% vs stock 9.84% on 13,207 cleaned test examples.
This is self-reported and within-domain; it does not prove spontaneous technical
speech superiority. Earlier personal technical codeswitch Whisper tests emitted
text on silence/noise controls; that outcome is not attributable to every stock
or fine-tuned Whisper version.

### Voxtral Mini 4B Realtime 2602

[Official model card](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602)
explicitly lists Russian among 13 languages and configurable streaming delay.
This is a meaningful 2026 alternative for continuous speech.
[Native C runtime](https://github.com/antirez/voxtral.c) exists; its README estimates
8.9 GB mapped model weights, up to 1.8 GB KV and 200 MB working buffers, plus a
separate Metal cache when applicable. It is substantially heavier than Qwen and
CPU BLAS is described as slow. No Deck accuracy/latency claim, no unsolicited
migration to another host. Keep as an accuracy/streaming research candidate,
not part of this two-model pilot.

### Nemotron 3.5 ASR Streaming 0.6B — important newly verified option

[Official model card](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b)
lists Russian as transcription-ready and a 2026 release. It is a cache-aware
FastConformer-RNNT with explicit `ru-RU` conditioning, punctuation and native
streaming chunks from 80 ms to 1.12 seconds. The official card reports Russian
FLEURS WER 9.17% with explicit language at 1.12 seconds, versus 10.03% auto
language. These are author results, not this speaker's performance.

Crucially, [current NeMo-Speech.cpp](https://github.com/NVIDIA/NeMo-Speech.cpp)
supports it natively alongside our Parakeet, including CPU/Vulkan builds.
The official model repository contains a Q8_0 GGUF of 742,090,464 bytes,
revision `ea30d66debe3740a08b573244286791d423d6b3e`, SHA-256
`3fc991d3badad7277c11030a7519832cddaf2057aafed6d4b25147e953a070b1`.
This is a closer operational fit than heavyweight Voxtral and deserves the next
bounded personal comparison if Qwen is inadequate. Verify current installed
0.1.0 engine compatibility first; do not assume latest README support applies
to the retained binary. No additional download/run/switch was performed.

### Canary v2 and Meta Omnilingual ASR

[Canary-1B-v2](https://huggingface.co/nvidia/canary-1b-v2) explicitly supports
Russian, while many adjacent NVIDIA variants are English-only. It is an offline
encoder-decoder alternative; direct integration with our retained engine is
not established.
[Meta Omnilingual ASR](https://github.com/facebookresearch/omnilingual-asr)
has 300M–7B CTC/LLM families and 2026 v2/streaming updates; broad language
coverage alone does not establish better Russian dictation. Official GPU-first
fairseq2 requirements and punctuation tradeoffs make it lower priority than
the directly compatible small streaming model. No candidate weights fetched.

### T-one and Cohere Transcribe

[T-one](https://github.com/voicekit-team/T-one) is an efficient streaming Russian
CTC model intended for **8 kHz telephony**. Its online decoder uses CTC beam
search and an external language model; the raw offline path is deliberately
weaker. This domain and resampling mismatch makes it a lower-priority candidate
for the retained wideband microphone audio.

[Cohere Transcribe 03-2026](https://huggingface.co/CohereLabs/cohere-transcribe-03-2026)
is a new 2B-class model but its declared 14 languages exclude Russian. Do not
recommend it merely because it is new. Model file access is gated; no credentials
or access acceptance were attempted.

## Community channels and limitations

Indexed Reddit discussions including
[Qwen vs Whisper](https://www.reddit.com/r/LocalLLaMA/comments/1qrbel2/qwen3_asr_17b_vs_whisper_v3_large/)
show interest and differing preferences. Direct fetch yielded no useful thread
body, so search snippets are only discovery evidence.

X public direct fetch failed and the authorized browser server is disconnected;
no full browser tools are exposed in this session. Indexed
[Qwen promotional post](https://x.com/ai_hakase_/status/2032291818805584063) is not
an independent Russian evaluation. No account actions, new login, profile copy
or paid API use. We have **not** reviewed a full live X reply thread and do not
claim community consensus from indexed marketing posts.

Other opened community evidence:
[Soniqo comparisons](https://cloud.soniqo.audio/ru/benchmarks) use FLEURS reading
and Mac/Metal rather than personal Russian dictation;
[Swift multilingual benchmark](https://github.com/holovchenko/qwen3-asr-swift/blob/main/docs/benchmarks/asr-wer.md)
labels FLEURS rows historical and hardware-specific;
[mxl fixed corpus](https://github.com/mxl/whisper-benchmark/blob/main/RESULTS.md)
has just two long files (one Russian). These are useful for runtime risks and
candidate discovery, not authoritative personal ranking.

## Practical implications

1. Natural multi-sentence speech remains the acceptance criterion. Artificial
   long pauses are not the desired workaround.
2. Sentence chunking alone is not an established fix: current reported failures
   are already 8–13 seconds and live gateway forwards WAV unchanged, no VAD.
3. Proper internal VAD/overlap/chunking can help long recordings only after
   proving that boundaries preserve words; it must not silently delete speech.
4. Capture source/gain/noise suppression in Omarchy remains unverified because
   SSH on the observed client address refuses connections. No generic claim
   that the microphone is fine; observed PCM excludes clipping and >=20 ms
   exact-zero runs in two samples only.
5. Avoid LLM text smoothing as a fake accuracy improvement. A fluent replacement
   is not recovery of the actual words spoken.

## Observed pilot baseline

Seven direct Parakeet replays succeeded, same frozen WAV hashes. The two
complaint outputs reproduce retained text exactly. Digital silence produced no
text; deterministic weak noise produced `And it's`. This is one negative-control
failure in this configuration, not a measured real-world hallucination rate.
All seven Qwen processes also completed with exit code zero and matched frozen
manifest/audio hashes; no transcript hints were used. It produced `Да.` on both
digital silence and weak noise, failing both negative controls in this exact
native BF16, forced-Russian, no-VAD configuration. This does not establish the
same behavior in every Qwen engine or with VAD, but blocks an unqualified swap.

Speech outcomes are mixed: one malformed complaint word became a plausible
hallucination-related verb, while a proper product name remained badly mangled;
another natural-speech opening gained a person's name, and a technical sentence
opening became more plausible. These are observations of candidate disagreement,
not scored correctness without listening and human reference. Do not publish
private utterances as reusable-source test fixtures.

Qwen total wall time for all seven independent process/model loads: 95.115 s.
Observed peak RSS: 7,041,720,320 bytes. Existing Parakeet direct replays were about
0.10–0.81 s per request on resident Steam Deck Vulkan. The different host,
precision, process startup and residence make these **not** a fair speed ratio;
Deck Qwen latency and resident CPU latency are unmeasured.

Both production services retained their exact PIDs and NRestarts=0 before/after.
No candidate switch or production restart. Candidate source and weights remain
available privately. Recommendation: keep current Parakeet for now; next
candidate is the smaller directly compatible Nemotron 3.5 ASR, with explicit
Russian and the same retained clips/negative controls. A Qwen VAD/port-parity
follow-up is a different bounded variant, not retroactive repair of this result.
