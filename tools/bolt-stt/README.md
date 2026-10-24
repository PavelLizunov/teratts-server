# Bolt dictation editor

This service runs the pinned NVIDIA Nemotron 3.5 Bolt E4B Q4_K_M through llama.cpp on Apple M4 Metal. It is the selected replacement for the optional FrogNano editor, not for ASR, Loqira, TTS, Kodak or the DSH chat model. Integration status and acceptance evidence are recorded in the [task specification](<../../docs/specs/bolt-smart-editor-primary.md>). The earlier [isolated assessment](<../../docs/specs/nemotron-bolt-isolated-assessment.md>) is contextual evidence, not acceptance of this service.

## Request path

Accepted Parakeet text passes through the existing dictionary, Loqira, final dictionary and optional opening cleanup. Configured Bolt edits both `default` and `smart` requests. Explicit `mode=raw` or `format=false` bypasses Bolt even with `smart=true`; these opt-outs also bypass Loqira. Dictionary and opening-cleanup switches remain separate. Historical Bonsai/FrogNano retain smart-only routing and their previous precedence. The transcription endpoint and response formats are unchanged.

The [explicit selector](<zzz-bolt-normalizer.conf>) sets `BOLT_NORMALIZER_CONFIG`. It takes priority over retained FrogNano and historical Bonsai selectors, including when the Bolt configuration is invalid or disabled; another model is never silently selected. The [example configuration](<bolt-normalizer.example.json>) uses the existing private token file without embedding credentials. Configuration is read at gateway startup.

The [client](<../bonsai-normalizer/bolt_normalizer.py>) accepts the model's actual paraphrase without lexical counts, ordered-word gates, deletion-only reconstruction or protected-byte shields. The prompt asks for neutral Russian, profanity/emotional-filler removal and short paragraphs while retaining the main request and facts. Meaning preservation is best effort, not a validated guarantee. Operational or protocol failures return the exact accepted post-cleanup source; valid text is returned unchanged by local code. An exactly identical candidate reports `unchanged`.

The bounded HTTP call has no retry or redirect and ignores proxy environment settings. Strict UTF-8 JSON decoding rejects duplicate keys, non-finite values, multiple choices and nonempty reasoning/tool fields. Assistant role, pinned model/revision, EOS, nonempty text and protocol markers remain checked. Ordinary labels such as `Ответ:` and `Результат:` are editable prose, not protocol channels. The gateway readiness response exposes configured model/revision without inference. The retained [deletion validator](<../bonsai-normalizer/bolt_cleanup.py>) is no longer called by Bolt.

## Service lifecycle

[The service](<bolt_service.py>) binds to an explicit Tailnet IPv4 address, normally port 8094, and authenticates health, metadata and inference with the existing bearer token. Health/metadata do not load model weights. Each accepted editing request starts a task-owned llama-server on a private loopback port, runs one non-streaming chat completion, stops/reaps the process and releases the shared vision lock before reporting success. There is no permanently resident Bolt model and no second-model fallback.

The GGUF has full SHA-256 `c8af2b8aea10a690a1d9491db744a9446660173cb38fc489612b556615a69612`, revision `1db54d5b12533ff1bcaa8e42cf4c667988a1f1be`. Startup verifies the full model hash; requests reject file-identity drift. A separately pinned runtime manifest covers the exact binary and dylib paths. Runtime b11459 is commit `f498f864fbc0472004ee1c3616c1188c68eb157f`; no global engine update is required.

The fixed neutral-rewrite prompt matches the gateway client exactly. Profile: greedy seed 42, thinking/conversational mode off, allocated context 4096, at most 3072 prompt tokens including automatic BOS and 512 output tokens, f16/f16 KV, mmap/lazy PLE, no cache/warmup/speculation. The native operation is fixed at an 18-second budget inside the client's 20-second ceiling, reserving 9 seconds for bounded cleanup and final counters. Absolute HTTP alarms cover internal requests and inbound framing; filesystem I/O, process creation and OS scheduling are not hard real-time guarantees. Cleanup failure stops serving while retaining process and lock ownership, without automatically reloading the model. Admission requires a 6.5 GiB native-page proxy; sampled reserve is 2 GiB and allowed new swap is 0.25 GiB. Native counters and sampled checks cannot establish instantaneous peak guarantees.

The downloaded GGUF/runtime reports text input/output only. Vision, video and audio are not enabled by this integration.

## Checks

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tools/bolt-stt -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python3 -B -O -m unittest discover -s tools/bolt-stt -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tools/bonsai-normalizer/tests
PYTHONDONTWRITEBYTECODE=1 python3 -B -O -m unittest discover -s tools/bonsai-normalizer/tests
```

Full ASGI/multipart checks require the existing Deck web environment and `BONSAI_ASGI_TEST=1`. All ordinary unit tests are model-free. The [rewrite acceptance harness](<../bonsai-normalizer/bolt_rewrite_acceptance.py>) starts a task-owned loopback HTTP server using installed gateway code, dictionary and the actual Bolt client/service, with synthetic ASR/Loqira stubs. Four fresh cases use a frozen semantic rubric plus manual meaning review, not exact-output scoring. Canonical exclusive fixture-hash/case-ID claims are independent of the output directory. Failed quality returns nonzero; consumed and uncertain cases are never replayed. The [prior harness](<../bonsai-normalizer/bolt_gateway_acceptance.py>) and its 12-case deletion-only results remain historical evidence and must not be used unchanged for rewrite routing. Neither harness verifies acoustic recognition or owner-field insertion.

## Scoped rollback

The installation retains the exact prior gateway copy and R76/FrogNano sources/configuration. To restore the previous selector, remove only the dedicated Bolt drop-in from the active gateway drop-in directory, reload user systemd and restart only `voice-gateway.service`. Restore the saved gateway copy if the new import seam must also be removed. The shared transport and historical clients remain unchanged. Verify Parakeet/Loqira readiness and raw/default bypass. Stop only the new Bolt LaunchAgent after confirming its request settled and its child was reaped. Retain model files, runtime, source and evidence; do not stop Kodak, FrogNano, Parakeet, Loqira, TTS or Clef.

## Verification status

The [rewrite task](<../../docs/specs/bolt-working-rewrite-20261024.md>) supersedes smart-only/deletion-only behavior. This source revision is awaiting deployment and fresh native rewrite checks; no rewrite quality pass is claimed yet.

### Retained pre-rewrite results

Bolt was deployed as the optional smart editor from source commit `d5174ee40e6ef05a4427c0d6683db4b1d3c576b3`, using the existing Mac Python 3.14 service environment and the installed Deck selector. The frozen installed-handler screen completed 12 once-only native calls: 10 quality passes and 2 failures, all HTTP 200/EOS. One model answer deleted a meaningful instruction and was rejected with exact accepted-source fallback; another left an initial lowercase letter after profanity deletion and failed the exact-output scorer. The prompt, scorer and outputs were not repaired to improve the score. See the [sanitized verification record](<primary-verification.json>) and [task status](<../../docs/specs/bolt-smart-editor-primary.md#current-status>).

Median editor latency was 2.952 seconds (range 2.511–6.222); minimum sampled available-page proxy was 3.001 GiB, maximum sampled child RSS 3.282 GiB and new swap 0 GiB. A separate final observation confirmed no native child, `loaded=false`, a free shared lock and unchanged protected service identities/hashes. Raw/default bypass and injected unavailable, timeout and rejected-edit fallback passed; smart with formatting disabled remained model-free. The editor remains selected as requested, but the two quality failures prevent claiming full quality acceptance or superiority over FrogNano. Real audio, owner-field insertion, concurrency, soak and an operational rollback were not tested.
