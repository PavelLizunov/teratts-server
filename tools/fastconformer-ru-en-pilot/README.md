# Isolated FastConformer RU/EN pilot

CPU ONNX RNNT prototype, not an activated speech backend. Production Parakeet,
gateway, dictionary and original recordings are not changed. No HTTP server or
service restart is needed.

## Dependencies and source

Use a dedicated virtual environment and the pinned `requirements.txt`. The
runner reuses the NeMo ONNX encoder/decoder/joiner interface and Kaldi-native
feature extraction from the [upstream reference](https://github.com/k2-fsa/sherpa-onnx/blob/6e7ea3e409f90aaf1541c87f21a013c4f20b9680/scripts/nemo/fast-conformer-hybrid-transducer-ctc/test-onnx-transducer-non-streaming.py).
Unlike that reference it does not add two seconds of silence, import Torch or
resample/downmix input. It accepts whole 16kHz mono PCM16 WAVs only.

Model downloads and original audio are private task artifacts, not repository
content. Code licensing does not relicense NVIDIA model assets; see the model
card's governing terms before redistributing assets.

## Prepare verified numerical artifacts

Extract original checkpoint YAML and referenced SentencePiece members without
loading the weight state. Place downloaded int8 ONNX files and `tokens.txt` in a
separate directory. Then:

```sh
python prepare_artifacts.py --original /private/original-artifacts \
  --export /private/int8 --output /private/prepared
```

Preparation reconstructs the aggregate vocabulary in the original configuration
order, compares every numerical ID against both original joint vocabulary and
export text, and records original language offsets and file hashes. It fails on
a mismatch and refuses to replace an existing bundle.

## Run a single trial

```sh
python run.py --artifacts /private/prepared --wav /private/original.wav \
  --audio-sha256 ORIGINAL_SHA256 --output /private/results/no-bias.json --no-bias
python run.py --artifacts /private/prepared --wav /private/original.wav \
  --audio-sha256 ORIGINAL_SHA256 --output /private/results/bias.json \
  --hints /private/hints.json
```

Hints are numerical language-aware paths from the original RU/EN tokenizers:

```json
[{"segments": [{"lang": "en", "text": "ChatGPT Pro"}]}]
```

Only RU/EN class IDs plus blank are eligible. Ordinary open-subword paths remain
available; this is not a closed lexicon. Context credit is applied before token
selection, unfinished prefixes are refunded, and `--no-bias` uses an empty graph
without inheriting global hints. Foreign-script unknown characters in hints
fail rather than being mapped to another language's first matching token.

Default beam is 4, context score 1.5, max 10 symbols per encoder frame, and one
CPU thread. Hypotheses merge equivalent emitted sequences/frame/symbol count
with log-add scores. State advancement follows the RNNT blank/nonblank rules.

Results retain numerical IDs, raw text, unmodified postprocessed text, acoustic
token probabilities, timestamp frame indices, provenance, runtime versions,
wall time and peak RSS. Existing trial receipts cannot be overwritten. The
runner checks resource limits between operations; `pilot.py` supervises the
child during blocking native ONNX operations. Its fixed `pilot-manifest.json`
contains exactly two original recording IDs, paths and hashes; it executes the
no-bias and bias cells sequentially and refuses a nonempty results directory.

```sh
python tools/fastconformer-ru-en-pilot/pilot.py /private/pilot-root
```

Selected pilot protections: 180 seconds per recording, 1536MiB process RSS,
2048MiB minimum available RAM, 256MiB maximum swap growth and 85C temperature.
These are method limits, not a user-imposed deadline or proven hardware maxima.

## Focused checks

```sh
python -m unittest discover -s tools/fastconformer-ru-en-pilot -p 'test_*.py'
```

These model-free checks cover finite-ID selection, numerical-language isolation,
context prefix refunds/optout and alignment-score merging. They do not measure
acoustic accuracy. See the [task contract](../../docs/specs/fastconformer-ru-en-pilot.md)
for the bounded two-recording pilot and retained no-repeat rules.

## Alternative methods

`alternative.py pilot ROOT MANIFEST` runs new CTC cells with either the original
KNF frontend or the source-aligned NumPy frontend. The manifest names a new
results directory and cells (`id`, `wav`, `audio_sha256`, `frontend`). Model and
token-map hashes are checked. Optional `precision` is `int8` (default) or `fp32`
for the pinned official exports. The two full-precision cells also left target
names and ordinary Russian text damaged; int8 alone does not explain the failure.
Whole-utterance CTC probabilities are retained as
NPZ alongside raw output. The alternate frontend implements NeMo 1.21 centered
STFT, global preemphasis, Slaney mel, additive log guard and feature normalization;
it is not claimed bit-exact with Torch. No silence is appended to the WAV.

`ctc_context.py --root ROOT --receipt CTC_JSON --output NEW_JSON` searches those
retained probabilities without rerunning the encoder. It preserves numerical
language IDs, CTC blank/nonblank mass and open vocabulary. Beam32 with no hints
and score2.5 hints did not recover the target names in the retained recordings.
Optional `--equalize-language-priors` divides each branch by its observed whole-
utterance prior, then preserves original per-frame pair mass and blank. This
removes a measured EN prior of only 0.005–0.010%, not a desired-text-derived score.
Adjusted sequence probabilities are labeled separately from raw acoustics.
The bounded FP32 observation recovered names only in the short clip but mixed
Latin pieces into Russian words and inserted an unwanted longer name in the
long clip. The method is retained for diagnosis, **not recommended for use**.

Context scoring now credits the union of covered token positions, so nested
hints such as ChatGPT and ChatGPT Pro no longer double-credit their shared
prefix. Optional `--word-language-continuity` enforces original tokenizer
branch continuity inside each word, allowing changes at SentencePiece word
boundaries or punctuation, without restricting ordinary open-subword paths.
Unknown IDs cannot create a boundary. The one observed combined repair removed
the unwanted Pro and had no within-word branch violations, but ordinary words
remained damaged and DSH was missed. It is still not a quality replacement.
Scores retain their adjusted-acoustic/context split; the old failed outputs
remain unchanged.

`run.py --frontend nemo --retain-encoder` also closes the previously unobserved
RNNT frontend branch. `pilot.py ROOT --manifest MANIFEST` accepts optional
`results_directory`, `frontend`, `retain_encoder`, and `variants` fields; the
original manifest defaults remain unchanged. The two new RNNT/no-bias runs with
the source-aligned frontend completed on Deck, but still emitted zero English
IDs and damaged technical names. Whole-process wall was 3.41/5.00 seconds and
high-water RSS 384.37/481.00 MiB. Retained encoder NPZ plus length/hash prevents
unnecessary future native inference. These observations do not justify another
blind coefficient sweep or a production replacement. The existing overlap-check expectation was updated to union
coverage; checks were not executed after the earlier platform denial.

`whisper_diagnostic.py pilot MANIFEST` is a **different, non-pair-constrained
quality diagnostic**, not an activated backend. It loads the pinned code-switch
fine-tune `coriollon/whisper-large-v3-turbo-russian-codeswitch` at revision
`bf64d2a976a268e35041f74233f889f951f0f676`, published CT2 assets only. It encodes each
whole WAV once without padding, then runs beam5 without hints and with the same
name context. It does not use VAD, crop audio, segment audio, rewrite transcripts
or infer a language restriction from script. Each branch keeps its raw IDs/text
and score. The JSON manifest specifies `model`, `results_directory` and
`recordings` with `id`, `wav`, `sha256`. Existing result directories are refused.

Use a separate venv with `faster-whisper==1.2.1`, `ctranslate2==4.8.2` and
`tokenizers==0.23.3`. Runtime versions and model-download hashes are recorded.
Method guards are 240s per whole recording including both decoder variants,
4096MiB process RSS, 2048MiB available RAM, 256MiB swap growth and 85C. These are
agent-selected ceilings, not capacity reservations. Exact Deck feasibility is
recorded in private result receipts, separately from local-host quality runs.

The fine-tune plus name context recovered the known technical names on both
retained clips locally and on Deck, while one ordinary Russian word remained
malformed and a small omission remained in the longer Deck output. The Deck
portability observation used about 954–1046MiB RSS, reached 66C and showed no
sampled swap growth. Complete processes including model load and both decoder
variants took 7.64s/15.65s for 5.80s/18.09s recordings; this is not persistent
endpoint latency. The local and Deck texts were not byte-identical. No human
gold/WER exists. Its shared multilingual vocabulary does **not** meet
the original hard RU/EN restriction, despite mixed-language fine-tuning. Thus it
is a promising quality result, not an unqualified replacement recommendation.

## MMS trained RU/EN adapters

`mms_pair.py pilot MANIFEST` is an isolated local-host diagnostic using publisher
`facebook/mms-1b-all` revision `3d33597edbdaaba14a8e858e2c8caa76e3cec0cd`.
The JSON manifest contains `model`, `results_directory`, and `recordings` with
`id`, `wav`, `sha256`. Verified safetensors and a `download-receipt.json` are
required; runtime network access is disabled. Use a task-only environment with
CPU Torch 2.5.1, Transformers 4.44.2, Accelerate 0.34.2, NumPy 1.26.4.

Each intact WAV gets two full encoder passes with the official eng/rus adapters.
Per-language adapters affect all transformer layers; one shared final encoding
would be incorrect. Separate head logits/IDs are retained before numerical
fusion. The decoder mixes both heads equally, combines their blanks, suppresses
reserved symbols, and permits only original eng/rus head-token IDs. English
154 classes and Russian 95 classes are publisher vocabularies, not invented
alphabet masks. Some head tokens use other scripts; this is not a semantic
language guarantee. Character vocabulary remains open; name context is applied
numerically before beam pruning, with no transcript replacement.

Equal head weighting is a fixed diagnostic assumption, not proven acoustic
language detection. No-context/context beam32 variants share retained logits.
Agent-selected protections: 600s/recording, RSS8192MiB, available-floor2048MiB,
swap-growth256MiB, 85C. This is not a Deck memory or latency claim, and does not
activate a production backend. Model license is CC-BY-NC4.0.

The first launch stopped before inference on a legacy `weight_g/weight_v` versus
Torch parametrization-name mismatch. The loader now migrates only this exact
two-key mapping and verifies unchanged tensor values. Other missing/unexpected
weights are errors; failed receipts remain intact.

Both acoustic runs then completed, but equal mixture blank probability erased
many Russian emissions. `mms_word_graph.py --model MODEL --receipt MMS_JSON
--output NEW_JSON` repairs that mechanism using retained logits: the active
head, including its own blank, persists within each word. Heads may switch at
word boundaries; ordinary open vocabulary remains available. The decoder has
180s/1536MiB guards and performs no acoustic pass. Its output no longer loses
letters en masse, but context still inserts wrong names and corrupts speech.
Neither MMS configuration is recommended as a replacement. The local full
process including both head passes and original mixture search took 31.04/48.06s
with high-water RSS4160.09/4466.41MiB. Subsequent word-state decoding took
4.04/15.47s separately; these are not Deck or persistent-endpoint timings.

## Independent language contributions

`mms_lid.py pilot MANIFEST` uses independent `facebook/mms-lid-126` at
`53da6e311f3ce48f324fe335924216187e3109a4`, with the same manifest schema,
verified safetensors, offline runtime and local-host external guards as MMS ASR.
There are no words/hints or transcript input. One official whole-recording
forward is observed; a projector hook retains temporal vectors. Applying the
published linear classifier per frame should average to the official global
logits, and the runner checks that identity without a second encoder pass.

The NPZ stores all126class contributions, RU/EN pair probabilities and exact
convolutional frame-center times. No waveform splitting or padding is used.
RU ID26 and EN ID2 come from the trained classifier map. This model was trained
for whole-utterance language identification, so time-local contributions with
global attention are **not validated language-switch timestamps**. A successful
aggregation check establishes implementation consistency, not localization
quality. Downloading or running it does not by itself solve the ASR requirement.

Observed LID on both intact recordings: all1193frames favor Russian; maximum
EN pair-conditional probabilities0.00131017/0.000479798. Mean frame logits
reproduce the official global output within1.44e-6. Thus extraction is
consistent, but the signal is not useful as switch guidance here. It was NOT
applied to ASR. Local process42.545/37.043s, RSS4051.430/4074.781MiB; no Deck run.

`diagnose_original.py --root PRIVATE_ARTIFACT_ROOT --output NEW_JSON` reads the
pinned original checkpoint with `weights_only=True`, compares preprocessing on
the retained whole WAVs using its saved window/mel bank, and matches the FP32
ONNX initializers to original tensors. It requires task-local Torch and ONNX1.17;
it runs no ASR model and writes exclusive JSON/NPZ evidence. Observed feature
maximum differences are7.546e-5/4.143e-5;575/609export tensors match exactly.
The remaining34depthwise-convolution tensors correspond to analytic BatchNorm
folding (separate retained diagnostic, maximum difference3.815e-6). This excludes
large observed feature/weight mismatches, not every possible graph/operator bug.

## Limits

Language-branch masking is not semantic language classification. Published
monolingual/multilingual training does not prove continuous code-switch quality.
The first fixed Deck pilot completed all four cells (two whole recordings,
with and without score-1.5 hints) without protective stops. Allowed numerical
IDs were respected, but every output used only Russian-branch IDs, the hints
did not change either transcript, and the target names were not recovered.
This version is not recommended for a production switch. Private result
receipts retain the exact wall-time/RSS measurements and original audio; no
human reference transcript/WER is available. Model-free checks were written,
but their execution was rejected by the platform action filter, so they are
not claimed as passed. Feature extraction follows the pinned exporter example rather
than claiming bit-exact Python NeMo preprocessing. No speculative text repair,
ITN or homophone substitution is applied.
