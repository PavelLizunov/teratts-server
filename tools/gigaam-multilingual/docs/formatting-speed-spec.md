# Restore GigaAM formatting and attempt bounded acceleration

## Requested outcome and authorization

User: «востанавливай все и попытайся ускорить гигу». Restore normal-input punctuation/case/paragraphs and contextual English spelling without paraphrasing, dropped words or following spoken instructions. Keep existing explicit dictionary rules. Attempt measured acceleration of the exact current GigaAM Large CTC model. Voice gateway/decoder and a speech-only formatter may be restarted within this task after warning; no DSH/TTS, provider, unrelated VM or OCR changes.

## Scope and invariants

- Existing Python FastAPI gateway and pinned PyTorch CPU decoder; reuse installed SAGE ONNX and/or Spark speech-formatting assets, no new large model downloads.
- Preserve exact GigaAM weights/revision, CPU float32 unless a separate accuracy-safe change is agreed. No Parakeet fallback. Preserve every sample and transformation stage, failure/model/runtime provenance, private rolling corpus, dictionary opt-out and default-off filler cleanup.
- Format defaults must actually run for GigaAM normal input; `mode=raw` and `format=false` bypass formatting. Failed/invalid/incomplete formatter output returns original content with an explicit status. Normal mode must never silently use smart action-item rewriting.
- A lexical fidelity check must reject additions, removals and substitutions apart from explicitly permitted English spelling spans. Do not globally convert ambiguous Russian combinations to English. Preserve URLs, code, identifiers, negation, numbers, filler words and repetition.
- Keep model loading offline, temporary listeners loopback-only, bounded CPU/memory/temperature. Persistent formatter is speech-only, not an agent/chat endpoint. Preserve old source/unit/config before deployment.

## Plan and verification

1. Inspect live units/resources/source and installed assets. Reuse old code only where appropriate; record search verdict. Record the formatting regression in the incident ledger.
2. One short existing-formatter screen: SAGE CPU versus retained Spark GPU speech-formatting, at most six synthetic cases, one known-answer smoke, <=15 min GPU time. Includes negation, command-as-data, English/Russian ambiguity, repetitions/numbers and long text. No full benchmark or soak.
3. Separate one-part bounded GigaAM performance experiment: profile actual target, fixed search and distinct confirmation recordings, immutable hashes/reference text/segments, controlled interleaving, no hints. At most three runtime-profile candidates, stop on three non-KEEP; profiler evidence must guide hypotheses. Accept only exact output/coverage identity, no memory/thermal pressure and practical noise-filtered latency gain. Report no accepted gain if none passes. No broad campaign.
4. Unit/handler/protocol tests including missing formatter, corruption/truncation, opt-outs, dictionary-after-format, raw provenance and failures. Tailnet actual request verifies normal formatted text, raw bypass and retained stages. Readiness must expose actual formatter availability, not claim ready from static settings.
5. Apply only tested changes, restart only scoped voice units, verify new source hashes/service state and rollback preservation. Update README and source-only Git backup. No private audio/transcripts/sample IDs/weights in Git.

## Material unknowns

SAGE can rewrite bilingual content; old Spark action-item prompt is unsuitable. Safe contextual English conversion cannot be guaranteed for arbitrary words from acoustically ambiguous input. CPU float32 may have limited speed gains; added formatting has its own latency, report decoder and end-to-end separately. No sustained load, reboot or thermal soak; independent reviewer route unavailable, self-review is not independent acceptance.

## State

Implemented and deployed with the authorized voice-only restart. Decoder/gateway PIDs 3114411/3114415, NRestarts=0. Exact model unchanged, four threads/400% quota. Guarded SAGE punctuation/case is active, `smart` no longer rewrites GigaAM into action items; contextual English supports explicit English cue + «ор нот», not arbitrary translation. Original filler/repetition retained. Search verdict: Extend existing SAGE/standard-library alignment; Spark rejected for translation/word changes and remains stopped. Screen required two prompt/config corrections; bounded synthetic runs, not broad benchmark.

Profiler: ~99% in torch native kernels. Search paired medians ~3.404→2.081 seconds (~39%); holdout ~5.382→3.733 (~31%), exact transcript/segment matches in every run. One accepted candidate, no quantization/model changes. Peak RSS ~2.9 GB, temperature <=74 C, available RAM ~12 GB. Immutable evaluator locked at `6a5f5b3`, candidate `70e95a9`, protected helper confirmation passed; schema-integration failures occurred before receipt acceptance and are not model failures.

All 54 scoped tests pass. Actual normal-input endpoint before/after medians on two recordings ~2.007→1.607 and 1.523→1.073 seconds (20–30%), including formatting; sequential pre/post is weaker evidence than paired decoder experiments. Live query bypass and dictionary opt-out accepted; every archive checked against actual flat corpus schema and response. First checker used wrong multipart fields and nested metadata/status assumptions; corrected query/flat-schema checks passed, production did not change. Rollback receipt/sources at `/home/deck/homelab/gigaam-format-speed/before`. Git source backup/docs remain final gate. Native isolation, concurrency, reboot, soak and natural-use accuracy remain unverified. No independent reviewer route available.
