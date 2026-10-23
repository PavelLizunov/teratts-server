# Bolt smart dictation editor

This service runs the pinned NVIDIA Nemotron 3.5 Bolt E4B Q4_K_M through llama.cpp on Apple M4 Metal. It is the selected replacement for the optional FrogNano editor, not for ASR, Loqira, TTS, Kodak or the DSH chat model. Integration status and acceptance evidence are recorded in the [task specification](<../../docs/specs/bolt-smart-editor-primary.md>). The earlier [isolated assessment](<../../docs/specs/nemotron-bolt-isolated-assessment.md>) is contextual evidence, not acceptance of this service.

## Request path

Accepted Parakeet text passes through the existing dictionary, Loqira, final dictionary and optional opening cleanup. Only effective smart mode invokes Bolt. Raw/default bypass it. Any failed or rejected edit returns the exact accepted post-cleanup source, not raw ASR. The existing transcription endpoint, response formats and mode precedence remain unchanged.

The [explicit selector](<zzz-bolt-normalizer.conf>) sets `BOLT_NORMALIZER_CONFIG`. It takes priority over retained FrogNano and historical Bonsai selectors, including when the Bolt configuration is invalid or disabled; another model is never silently selected. The [example configuration](<bolt-normalizer.example.json>) uses the existing private token file without embedding credentials. Configuration is read at gateway startup.

The [client](<../bonsai-normalizer/bolt_normalizer.py>) reuses the bounded, no-retry HTTP transport and inherited lexical checks. Its response decoder rejects duplicate keys, non-finite values, multiple choices and nonempty reasoning/tool fields. The gateway readiness response exposes the configured editor model/revision without calling it. It checks model/revision, normal completion, protocol and lexical invariants, then validates the model's actual deletions against a finite [source-position policy](<../bonsai-normalizer/bolt_cleanup.py>). Quotes/code/technical strings/literal mentions are shielded. Word substitution, including neutral replacements for curses, is rejected under the deletion-only prompt. Unsupported changes return the exact source. A valid unchanged model answer remains unchanged: Bolt is not a trigger for independent R76 local cleanup. This finite guard is not a universal semantic-equivalence classifier; unsupported slang may remain or cause fallback.

## Service lifecycle

[The service](<bolt_service.py>) binds to an explicit Tailnet IPv4 address, normally port 8094, and authenticates health, metadata and inference with the existing bearer token. Health/metadata do not load model weights. Each accepted editing request starts a task-owned llama-server on a private loopback port, runs one non-streaming chat completion, stops/reaps the process and releases the shared vision lock before reporting success. There is no permanently resident Bolt model and no second-model fallback.

The GGUF has full SHA-256 `c8af2b8aea10a690a1d9491db744a9446660173cb38fc489612b556615a69612`, revision `1db54d5b12533ff1bcaa8e42cf4c667988a1f1be`. Startup verifies the full model hash; requests reject file-identity drift. A separately pinned runtime manifest covers the exact binary and dylib paths. Runtime b11459 is commit `f498f864fbc0472004ee1c3616c1188c68eb157f`; no global engine update is required.

The fixed editorial prompt matches the prior isolated screen. Profile: greedy seed 42, thinking/conversational mode off, allocated context 4096, at most 3072 prompt tokens including automatic BOS and 512 output tokens, f16/f16 KV, mmap/lazy PLE, no cache/warmup/speculation. The whole native operation has an 18-second budget inside the client's 20-second ceiling. Admission requires a 6.5 GiB native-page proxy; sampled reserve is 2 GiB and allowed new swap is 0.25 GiB. Native counters and sampled checks cannot establish instantaneous peak guarantees.

The downloaded GGUF/runtime reports text input/output only. Vision, video and audio are not enabled by this integration.

## Checks

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tools/bolt-stt -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python3 -B -O -m unittest discover -s tools/bolt-stt -p 'test_*.py'
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tools/bonsai-normalizer/tests
PYTHONDONTWRITEBYTECODE=1 python3 -B -O -m unittest discover -s tools/bonsai-normalizer/tests
```

Full ASGI/multipart checks require the existing Deck web environment and `BONSAI_ASGI_TEST=1`. All ordinary unit tests are model-free. The [native acceptance harness](<../bonsai-normalizer/bolt_gateway_acceptance.py>) uses installed gateway code, dictionary/opening cleanup and actual Bolt HTTP with stubbed ASR/Loqira, fresh frozen cases and canonical exclusive fixture-hash/case-ID claims, independent of the result directory. Failed quality returns a nonzero exit status. Consumed and uncertain claims are never reset. It must not replay an existing case. This verifies the editor seam, not acoustic recognition or insertion into the owner's active field.

## Scoped rollback

The installation retains the exact prior gateway copy and R76/FrogNano sources/configuration. To restore the previous selector, remove only the dedicated Bolt drop-in from the active gateway drop-in directory, reload user systemd and restart only `voice-gateway.service`. Restore the saved gateway copy if the new import seam must also be removed. The shared transport and historical clients remain unchanged. Verify Parakeet/Loqira readiness and raw/default bypass. Stop only the new Bolt LaunchAgent after confirming its request settled and its child was reaped. Retain model files, runtime, source and evidence; do not stop Kodak, FrogNano, Parakeet, Loqira, TTS or Clef.

## Verification status

Implementation and model-free integration are being verified before deployment. Final native counts, installed commit and observed limitations belong in the task record; preparation alone is not a deployed or accepted result.
