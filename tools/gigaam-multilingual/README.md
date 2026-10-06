# GigaAM Multilingual: active Deck source snapshot

The user-approved speech activation runs **ai-sage/GigaAM-Multilingual, Large CTC**, revision `3905cd51c3ed4e88c8edf33f3302969ba480a327`. It is the exact model from the paired pilot, not legacy GigaAM v3, SAGE or Ultra. Runtime: Python 3.13, PyTorch/Torchaudio 2.10.0+cpu, CPU float32, two threads, greedy CTC without punctuation.

## Integration

The [decoder adapter](<gigaam_multilingual_server.py>) binds only to loopback port 10002. The [gateway](<deploy/gateway-server.py>) selects `gigaam_multilingual` via the [drop-in](<deploy/gigaam-multilingual.conf>) and preserves `https://steamdeck.tail9fd337.ts.net/v1/audio/transcriptions`. These are deployment-specific snapshots, not a generic installer. The gateway's unset environment still selects its legacy backend; the drop-in is required for this activation.

The [unit](<deploy/gigaam-multilingual-stt.service>) caps memory at 6 GiB and CPU at 200%. Model/source/config hashes are checked before loading official local classes with `weights_only=True`. The gateway checks the decoder weight SHA; failures do not silently use Parakeet. Existing GitHub, Omarchy, plugin and ChatGPT/Pro rules, dictionary opt-out, default-off cleanup and private corpus collection remain intact. Success and failure provenance records the new model/runtime.

Weight SHA-256: `c3fabefb50b41f08f4d7ad44e02c26c37d242882704cdcca2ebd98e45eff73d1`.

Verified deployed source hashes:
- Decoder adapter: `8a35a11a699aee43bf35f17b395703523cc37da39795cc8c3d15c038050c8c46`.
- Gateway: `4445ef1628297c135390c38652d0fa87507dbc19c14480920cc189816a330bf6`.

## Checks and observed latency

Run source-only tests from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/gigaam-multilingual/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/stt-dictionary/tests -v
```

Python with NumPy is needed for decoder PCM tests; no model weights or production dependencies are loaded by these tests. Gateway/archive tests compile the actual handler from the deployed-source snapshot. The full ModelForge activation verification passed 46 tests: decoder 2, gateway/archive 21, telemetry 9 and spelling 14.

On Deck, 7.978-second and 12.863-second staged recordings decoded in approximately 3.41 and 3.84 seconds. A 25.727-second repeated-input request completed in 8.77 seconds with continuous sample coverage. Live synthetic default/opt-out requests took 2.37–2.52 seconds; dictionary behavior and success/failure provenance were checked. Readiness, unit state and deployed hashes were rechecked during completion without a restart or new speech submission.

## Limits and rollback

- CPU inference is slower than former Vulkan Parakeet. Natural-use accuracy and preference remain unverified; the paired trial is not a gold-transcript accuracy result.
- 10 MiB WAV limit and 120-second upstream timeout. Continuous nonoverlapping chunks of at most 25 seconds use quiet-window cuts, not neural VAD; words/context at cuts may be lost.
- No reboot, thermal soak or sustained concurrency/load test. Python socket guarding/offline settings are not proven native network isolation. Thread-flood resistance is unproven.
- Parakeet is stopped/disabled, but its runtime, weights, unit and old gateway/drop-in snapshots remain on Deck. Rollback requires fresh authorization and leaves corpus, feedback, dictionary, DSH and TTS unchanged.

Activation consumed one authorized gateway restart. This completion pass changes only documentation/source backup and performs read-only checks. No audio, natural transcripts, corpus sample identifiers, weights, credentials or model assets are included here. See the [task record](<docs/activation-spec.md>) for scope and verification boundaries.
