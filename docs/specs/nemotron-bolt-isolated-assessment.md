# Nemotron 3.5 Bolt E4B isolated assessment

## Decision and scope

NVIDIA Nemotron 3.5 Bolt E4B Q4_K_M runs on the Apple M4 through Metal and passed four frozen synthetic Russian deletion-only editing cases. This is a promising candidate result, not a production recommendation or evidence of superiority to FrogNano. Installed R76 remains unchanged. No R77 or Bolt deployment, gateway integration, private-dictation replay, audio inspection, service restart or owner-PC change occurred.

The existing FrogNano system prompt was reused without modification. The candidate was reached directly through llama.cpp `/v1/chat/completions`, not through the installed transcription gateway. Therefore this screen does not verify raw/default bypass, exact-source fallback, authentication integration or end-to-end user routing for Bolt.

## Pinned artifacts

| Component | Identity |
| --- | --- |
| Model repository | `nvidia/NVIDIA-Nemotron-3.5-Bolt-E4B-4GB` |
| Model revision | `1db54d5b12533ff1bcaa8e42cf4c667988a1f1be` |
| Artifact | `Nemotron-3.5-Bolt-E4B-Q4_K_M.gguf` |
| Exact bytes | 6,180,446,208 (5.756 GiB), despite the 4GB repository label |
| Model SHA-256 | `c8af2b8aea10a690a1d9491db744a9446660173cb38fc489612b556615a69612` |
| Runtime | Official llama.cpp b11459 macOS ARM64 archive |
| Runtime commit | `f498f864fbc0472004ee1c3616c1188c68eb157f` |
| Archive SHA-256 | `04cd4ab4fd748af1abc02d8d1759b55121141a377c97c297192e9608de2e8c4e` |
| Runtime-reported parameters | 7,518,069,290 |
| License advertised by model card | OpenMDW-1.1 |

The model download and complete checksum were verified before loading. The initial transfer incident recovered without reboot or production-service restart; its root cause remains unknown. An SSD/I/O explanation is not established.

## Method and correction

One slot, allocated context 4096, f16/f16 KV, batch 512, ubatch 128, all eligible layers offloaded, mmap with lazy per-layer token embeddings, no speculative decoding, no warmup, no prompt/checkpoint cache. Sampling: temperature 0, top_p 0.8, top_k 20, min_p 0, repeat penalty 1, presence penalty 0, seed 42, maximum output 512. Thinking and conversational mode were explicitly disabled in template settings. Actual prompts occupied 211–240 tokens, not 4096.

Screen 1 stopped before generation because its guard incorrectly required a textual BOS. In this runtime, the tokenizer automatically adds BOS and the chat renderer removes the duplicate textual BOS. Both `/apply-template` and chat completion use the same OpenAI-compatible parser. The correction requires equality of the entire system/user/model prompt without textual BOS, tokenizes with automatic special tokens, requires one leading BOS token 2 and retains rendered text before validation. No case, system prompt, sampling setting or scorer was changed. Screen 1 remains preserved; its lost rendered bytes cannot be reconstructed as an observed receipt.

Four offline unittest methods passed. Independent-context source/fixture review verified corrected runner SHA-256 `ca4636ec31a546c2a59e312c416db22d6f144d8d51b50eea4540e708419e40ac`. This review did not itself execute the model.

Screen 2 submitted each previously untouched case once. Four intent receipts and four raw responses exist. Screen 1 consumed zero generation requests; screen 2 consumed four. There were no inference retries or remaining requests in this finite screen.

## Observed quality and latency

The scorer requires exact expected text after whitespace normalization, not merely a valid HTTP response or EOS.

| Frozen synthetic case | Observed result | Request wall time | Input/output tokens |
| --- | --- | ---: | ---: |
| Neutral control | Unchanged; numbers, negation and condition retained | 2.151 s | 212 / 30 |
| Standalone profanity | Removed; service failure and file/journal instructions retained | 1.431 s | 211 / 25 |
| Protected quotation | Outside profanity removed; quoted profanity, build identifier and embedded command retained verbatim | 2.443 s | 240 / 52 |
| Substantive criticism | Emotional opening removed; 43-versus-8-second claim, criticism and access-check instruction retained | 2.029 s | 229 / 40 |

Exact expected results: **4/4**, including **3/3 cleanup cases** and **1/1 neutral control**. All responses ended at native EOS, without truncation. Native verbose diagnostics reported the `peg-gemma4` parser and bare model generation prefix. Their detokenized input equaled the saved render plus automatic BOS; token counts agreed. No nonempty reasoning field or raw thought-channel marker appeared. This does not prove a general sampler-level ban on reasoning tokens.

Weighted native decode throughput was **28.97 tokens/s**, computed as `sum(predicted_n - 1) / sum(predicted_ms / 1000)`. This excludes the first generated token and is distinct from request wall time. The first request included a colder prefill. There is no same-profile paired FrogNano baseline, so no causal speedup claim is supported.

The whole second runner interval was **8.946 s**, within the 15-minute residency budget. Individual requests stayed below their 20-second wall deadline. The initial guard-only interval was 6.230 s; combined recorded runner intervals were 15.177 s, not a measurement of full task/download time or exact GPU busy time.

## Memory, placement and restoration

Apple M4 has 16 GiB unified RAM. The logs confirm Metal selection, 43/43 eligible layers offloaded and lazy reads for the 2.789 GiB per-layer token embedding tensor. These are placement observations, not proof that every operation runs on GPU.

All quantities below use GiB:

- Runtime-reported Metal mappings/buffers: model mapping **5.741**, KV **0.0918**, compute **0.0474**, approximately **5.880** combined. Host model mappings were **3.453** plus **0.0124** compute and **0.0010** output. These are overlapping unified-memory/file mappings; do **not** add them as independent physical consumption.
- Available-memory proxy (free + inactive + speculative native pages): **7.759** before, sampled minimum **3.100**, **7.874** after. Required sampled reserve: **2.000**. The proxy is not a guaranteed allocatable-memory figure.
- Maximum sampled candidate RSS: **3.278**. RSS and mappings do not establish the total physical peak or whole-device consumption.
- Occupied system swap: **2.242** before and after, with **0.000** observed growth; allowed growth was 0.250.

There were 21 memory observations including post-response observations; the monitor sampled at approximately 0.5-second intervals. Unobserved transients are not excluded. Candidate process exited 0 and was reaped. Shared vision lock was released. Protected source/configuration hashes and service process identities matched before/after, and FrogNano/Bonsai were healthy and unloaded. Kodak remained on its existing `minicpm_q8 / edge448 / plain` configuration.

## Modalities

The official GGUF card advertises text input/output. Runtime `/props` reports vision, video and audio false; `/v1/models` reports text input/output only. The inspected published artifact inventory has no matching vision projector. Consequently **usable vision is not established for this exact GGUF/runtime**, and no image/audio inference was run.

The pinned BF16 revision `49843eed8db1f1c616c47af75cfd36e07aec0667` contains 658 vision-tower tensors plus one vision projection and 751 audio-tower tensors. Architectural components and modality markers in a template do not establish an executable multimodal path for the downloaded GGUF. BF16 deployment, projector conversion and vision acceptance remain deferred.

## Limits and next decision

This tiny synthetic screen establishes native text compatibility and success on these four cases only. It does not establish robustness on real dictations, arbitrary slang, corrupted ASR, long context, service concurrency, reliability, or deployment suitability. Production load and soak were not run. No private dictation or acoustic evidence is published here.

The completed assessment supports retaining Bolt as a candidate. Any later evaluation should be separately identified and use fresh, authorized inputs rather than replaying these consumed cases or private requests. Production R76 remains the baseline.

## Sources and evidence

- [Official GGUF repository at the pinned revision](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Bolt-E4B-4GB/tree/1db54d5b12533ff1bcaa8e42cf4c667988a1f1be)
- [Pinned llama.cpp chat rendering](https://github.com/ggml-org/llama.cpp/blob/f498f864fbc0472004ee1c3616c1188c68eb157f/common/chat.cpp)
- [Pinned API handlers](https://github.com/ggml-org/llama.cpp/blob/f498f864fbc0472004ee1c3616c1188c68eb157f/tools/server/server-context.cpp)
- [Pinned raw completion diagnostics](https://github.com/ggml-org/llama.cpp/blob/f498f864fbc0472004ee1c3616c1188c68eb157f/tools/server/server-task.cpp)

Private receipts are retained outside Git in the task workspace: screen-1, screen-2, model verification, runner/test snapshots and resource samples. Only this sanitized assessment is intended for the repository checkpoint.

### Documentation verification

PASS: numerical claims reconcile with retained native receipts; capability, quality, memory and deployment claims are separated. PASS: no private transcripts, credentials, fabricated quotes or superiority claims. PASS: the conclusion remains limited to this candidate/profile and four consumed synthetic cases.
