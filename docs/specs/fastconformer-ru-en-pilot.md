# Isolated FastConformer RU/EN prototype

## Authorization and intended result
Direct user on 2026-10-12: «Давай реализовываю потестим» following explicit checkpoint/runtime/pilot proposal. Implement a task-local ASR prototype and run a bounded recording-matched pilot, not a production replacement. Downloads and isolated dependencies are authorized. Prior research identifies FastConformer Hybrid Large P&C and numerical language partitions as the candidate.

## Scope and invariants
- Extract original checkpoint config and language SentencePiece artifacts; preserve original offsets/class order and match against exported tokens. Never infer language labels from alphabet or archive name.
- Python ONNX Runtime CPU runner based on pinned upstream reference, without Torch/librosa or its two-second silence padding. Whole 16kHz mono PCM16 recordings only, no segmentation/resampling/padding or repeated production baselines.
- Open-subword beam decoding, explicit RU+EN allowed IDs plus blank, numerical context paths before candidate selection. Dictionary optout creates no bias graph. Numeric IDs/raw text stay separate from optional formatting; no semantic rewriting.
- Production services, gateway/dictionary and original WAVs unchanged. No restart, private external upload, training or broad campaign. Private WAVs, models, receipts and results remain outside Git.
- Local source belongs to this repository; commit/push only task files. Any remote execution/build uses exact committed SHA with existing pinned SSH alias.

## Pilot and verification
- Two retained whole natural recordings. One pair-constrained no-bias and one pair-constrained bias configuration per recording, sequential, no repeated trials to improve score. Failed/unknown trials preserved.
- Before inference inspect Deck RAM/storage/ABI/temperature/fan. Selected protective limits (method defaults, not user deadline): 85C stop, minimum 2048MiB MemAvailable, maximum 256MiB swap growth, maximum 1536MiB child RSS, 180s per recording.
- Record audio/checkpoint/export/runtime/source hashes and revisions; allowed IDs, bias paths/score, numeric output IDs, raw and separately postprocessed text, elapsed and peak RSS. Invalid forbidden ID is an implementation defect, not allowed acoustic result.
- User requested tests: focused dependency-light decoder/artifact checks plus direct two-recording pilot. No independent review or broad benchmark.

## Material unknowns
Exact checkpoint contents, archive export correspondence, installed runtime ABI, mask/context performance and Deck quality/resource cost. Language-branch exclusion cannot guarantee semantic language identity or accurate code-switching. No human gold transcript/WER exists. Licensing uses model card governing terms; do not relicense weights under repository code license.

## Observed delivery
Original checkpoint downloaded and tokenizers/config extracted without deserializing original weight state. Concrete int8 export matches original joint and all ten language vocabularies; EN512–767, RU1280–1535, blank2560 confirmed. Isolated Deck venv and committed Python decoder executed four fixed acoustic cells successfully. All output IDs allowed, but all were Russian-branch; score1.5 EN name paths changed neither transcript and did not recover target names. Production services remained active with unchanged PIDs. No replacement recommendation from this pilot. Model-free test invocation was blocked by platform ACTION_FILTER; do not retry or disguise it. Private transcripts/receipts stay outside Git.

## Authorized alternative-method continuation
The user now requests «Забери задачу и попробуй решить проблему, используя другое модели и или методы». The first four-cell pilot is retained, not repeated or overwritten. Current goal is the actual mixed-language problem, not merely another completed script. Downloads/task-local implementation and bounded new configurations remain in scope; no production switch/restart, segmentation, audio padding, private external upload or training.

First causal alternative: CTC head removes RNNT prediction-state language lock. Read exact NeMo 1.21 feature source to implement its center-aligned STFT/mel frontend in NumPy rather than assuming the existing KNF snip-edge framing is equivalent. Numerical masks and original tokenizers remain unchanged. Internal STFT reflection is part of model feature extraction, not additional waveform/silence appended to the recording. Compare genuinely distinct CTC/frontend configurations; do not rerun old Parakeet or old RNNT baseline. Preserve every failed/consumed cell. If CTC shows an acoustic route to names, use bounded numerical context decoding before output, not semantic transcript repair. Resource protections remain as above. No unit-test retry after earlier platform denial.

## Search verdict
Extend — pinned FastConformer ONNX reference inference plus task-local masked numerical decoder. Reference/source path and language partitions already researched; existing repository pilots provide hash/RSS conventions but no matching decoder. Python minimizes remote build/dependency surface versus rebuilding all sherpa for API bindings; preserve numerical IDs directly.
