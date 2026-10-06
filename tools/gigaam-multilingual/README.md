# GigaAM Multilingual: active Deck source snapshot

The user-approved speech activation runs **ai-sage/GigaAM-Multilingual, Large CTC**, revision `3905cd51c3ed4e88c8edf33f3302969ba480a327`. It is the exact model from the paired pilot, not legacy GigaAM v3, SAGE or Ultra. Runtime: Python 3.13, PyTorch/Torchaudio 2.10.0+cpu, CPU float32, four threads, greedy CTC with gateway punctuation/case restoration through SAGE ONNX. Model weights/revision remain unchanged.

## Integration

The [decoder adapter](<gigaam_multilingual_server.py>) binds only to loopback port 10002. The [gateway](<deploy/gateway-server.py>) selects `gigaam_multilingual` via the [drop-in](<deploy/gigaam-multilingual.conf>) and preserves `https://steamdeck.tail9fd337.ts.net/v1/audio/transcriptions`. These are deployment-specific snapshots, not a generic installer. The gateway's unset environment still selects its legacy backend; the drop-in is required for this activation.

The [unit](<deploy/gigaam-multilingual-stt.service>) caps memory at 6 GiB and CPU at 400%. Model/source/config hashes are checked before loading official local classes with `weights_only=True`. The gateway checks the decoder weight SHA; failures do not silently use Parakeet. Existing GitHub, Omarchy, plugin and ChatGPT/Pro rules, dictionary opt-out, default-off cleanup and private corpus collection remain intact. Success and failure provenance records the new model/runtime.

Weight SHA-256: `c3fabefb50b41f08f4d7ad44e02c26c37d242882704cdcca2ebd98e45eff73d1`.

Verified deployed source hashes:
- Decoder adapter: `9d1cc720866b028cc038a034c52246f29488d1e63a4604d132abefcd7d2127ac`.
- Gateway: `371fc7438334ce5dd8dcb16be56b593f50343fe662ce6c0221b51f21916243fd`.

## Checks and observed latency

Run source-only tests from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/gigaam-multilingual/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/stt-dictionary/tests -v
```

Python with NumPy is needed for decoder PCM tests; no model weights or production dependencies are loaded by these tests. Gateway/archive tests compile the actual handler from the deployed-source snapshot. The restoration verification passed 54 ModelForge tests: decoder, gateway/archive, telemetry, spelling and formatting fidelity. The portable snapshot has 31 decoder/gateway/archive/formatting tests plus 14 spelling tests.

On Deck, 7.978-second and 12.863-second staged recordings decoded in approximately 3.41 and 3.84 seconds. A 25.727-second repeated-input request completed in 8.77 seconds with continuous sample coverage. Live synthetic default/opt-out requests took 2.37–2.52 seconds; dictionary behavior and success/failure provenance were checked. Readiness, unit state and deployed hashes were rechecked during completion without a restart or new speech submission.

## Restored formatting and confirmed speed change

Normal GigaAM requests use [guarded SAGE formatting](<speech_formatting.py>): punctuation/case with original words, numbers, negations and repetitions retained. If SAGE changes words, only safe punctuation between aligned source words is projected; failed/incomplete output falls back explicitly. Raw candidate and all stages stay in the private corpus. `mode=raw` and `format=false` bypass formatting; `dictionary=false` separately bypasses spelling rules. `mode=smart` for GigaAM no longer makes action-item lists.

Explicit English context supports «английское выражение ор нот» → «английское выражение or not». Arbitrary transliteration is not implemented: retained Spark changed/translated Russian in the finite screen, so it remains stopped. Existing dictionary recognizes standard «плагин» forms, not arbitrary acoustic variants such as «плогин». Paragraph/sentence quality is not guaranteed on long segmented text.

The four-thread candidate preserved exact transcripts/segment boundaries across three interleaved pairs on each split. Search workload median: 3.404→2.081 seconds (~39%); separate confirmation: 5.382→3.733 (~31%). One candidate accepted, not a broad campaign. Actual endpoint including formatting: initial before/after medians 2.007→1.607 and 1.523→1.073 seconds; query-control repeat 1.702/1.075 seconds. Short-run end-to-end gain is ~15–30%, not universal. See [full evidence/limits](<docs/formatting-speed.md>), [restoration task record](<docs/formatting-speed-spec.md>) and [protected experiment ledger](<perf/state.jsonl>). Measurements/evaluator in Git contain hashes and timings only, no natural transcript/audio. Model output references stay private.

## Limits and rollback

- CPU inference is slower than former Vulkan Parakeet. Natural-use accuracy and preference remain unverified; the paired trial is not a gold-transcript accuracy result.
- 10 MiB WAV limit and 120-second upstream timeout. Continuous nonoverlapping chunks of at most 25 seconds use quiet-window cuts, not neural VAD; words/context at cuts may be lost.
- No reboot, thermal soak or sustained concurrency/load test. Python socket guarding/offline settings are not proven native network isolation. Thread-flood resistance is unproven.
- Parakeet is stopped/disabled, but its runtime, weights, unit and old gateway/drop-in snapshots remain on Deck. Rollback requires fresh authorization and leaves corpus, feedback, dictionary, DSH and TTS unchanged.

The later user-authorized restoration restarted only decoder/gateway. Exact pre-restoration source/unit and receipt remain in `/home/deck/homelab/gigaam-format-speed/before` for scoped rollback. No audio, natural transcripts, corpus sample identifiers, weights, credentials or model assets are included here. See the [task record](<docs/activation-spec.md>) for scope and verification boundaries.
