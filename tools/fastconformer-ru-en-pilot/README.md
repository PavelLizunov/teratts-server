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

## Probability-only LM fusion on retained CTC scores

`ctc_lm.py pilot MANIFEST` runs a new isolated decoder using retained FP32 CTC
scores. The manifest supplies private artifact root, pinned ruGPT3-small model,
new result directory and two original acoustic/context receipts. The scorer
never calls `generate`: only allowed numerical RU/EN acoustic paths can appear.

Fixed diagnostic parameters are beam32, prebeam64, LM weight0.3, completed-word
bonus1.0 and context0/2.5. The existing prior equalization and word-language
continuity remain. The prebeam is an explicit bounded approximation; not all
possible paths receive LM scoring. Full provisional prefixes are scored during
search, with text+EOS at finish. Scoring only completed words was observed to
reward unspaced paths until an end-of-decode penalty; this mechanism is repaired
without changing coefficients. The word bonus counts completed words only.
Full-prefix byte-BPE
retokenization and cached common ancestors handle token merges. LM scores and
CTC masses remain separate. A direct teacher-forced score of each best output
checks the actual cached-score calculation without rerunning audio or ASR.

The pinned checkpoint is loaded with `weights_only=True` and strict parameter
matching. Legacy causal-mask buffers are checked before removal; learned
weights are not ignored or trained. Local-only guards are600s per recording,
RSS4096MiB, available-memory floor2048MiB, two CPU threads and a256MiB KV cache.
Completed variants and failed attempts are retained. Language-model training
on RU/EN text is not acoustic bilingual training and is not a replacement for
the original numerical token constraint. No quality result is implied by this
implementation or by successfully loading its weights.

Observed repaired LM fusion: short top output still misses ChatGPT Pro (the
third hypothesis contains it), long top output contains DSH but corrupts ChatGPT
and ordinary Russian. All numerical restrictions hold; cached LM sums match
direct scores within1.71e-5. Local wall88.126/195.777s including both hint modes,
RSS1453.191/1920.980MiB. No Deck run; not a replacement recommendation. The
failed initialization and deferred-word-cost outputs are preserved separately.

`rnnt_ilm.py --root PRIVATE_ROOT --output NEW_JSON` diagnoses language preference
along historical RNNT token paths, not a new transcription. A derived task-local
ONNX joiner removes the complete projected acoustic term including its bias;
learned weights remain unchanged. It reads retained encoder arrays and replays
the stored predictor path. Observed English pair fraction averages0.427/0.385
without acoustics, but falls below1e-18 with acoustics. This does not support
subtracting a dominant Russian internal language prior. Separate original-FP32
predictor/joint observations show2/62 and7/146changed token rankings on the same
path; quantized tensor maps and gate order are verified. Full FP32 decoding is
still unobserved; historical-path differences do not establish better accuracy.

## Original FP32 RNNT decoder boundary

`rnnt_fp32.py pilot MANIFEST` loads the verified original checkpoint's frozen
embedding, one-layer640LSTM and three-affine/ReLU joint. It reuses retained
whole-recording encoder arrays, not waveform input or a new encoder pass. The
manifest has the same shape as the CTC-LM manifest but points `model` to the
original archive and each receipt to its RNNT result. Strict11tensor shapes,
hashes and original language-token map are recorded. Search remains beam4,
max10symbols per frame, hints0/1.5, and original RU/EN numerical restriction.
There is no LM scorer or new prior correction in this isolation experiment.
Local protection is600s/RSS4096MiB; a successful run is not a quality claim.
The first run on retained int8encoder finished in7.511/14.520s with671MiB RSS,
but both hint modes emitted zero English tokens; the quality requirement failed.

`recover_encoder.py --root PRIVATE_ROOT --output NEW_DIRECTORY` recovers hidden
activations from existing full-class FP32 CTC log probabilities. Centering across
classes removes the logsoftmax scalar; the known centered2561x512projection is
full rank (condition80.56). Double least-squares must reproduce log probabilities
within0.001 before saving a FP32 encoder array compatible with `rnnt_fp32.py`.
This is a numerical reconstruction, not a new encoder pass or bit-identical
claim. All2561classes participate in inversion, not the later RU/EN mask.

## Separately trained Russian and English specialists

`specialist_pair.py pilot MANIFEST` runs pinned `bond005/wav2vec2-large-ru-golos`
and `facebook/wav2vec2-large-960h-lv60-self` sequentially on each whole recording.
Both use the same convolution frame geometry (20ms stride,400sample receptive
field); no frame interpolation or waveform segmentation is used. Original
checkpoints load with `weights_only=True`, an exact legacy positional-weight
name migration, strict complete keys and unchanged tensor values. All raw head
probabilities are retained before reserved tokens are masked.

The existing head-state word graph allows EN IDs0–31 and RU IDs32–68 by trained
model origin, with a separate local blank0 per head; specials1/2/3 cannot emit.
A head persists inside each word, including blank frames. Search is beam32,
context0/2.5. Published English character IDs are uppercase; only hint encoding
uses uppercase, not postprocessing. Head scores are not calibrated language
probabilities. This is two monolingual models, not a jointly bilingual checkpoint.
Local600s/RSS8192MiB supervision comes from the existing MMS runner; no Deck
readiness or quality claim follows from downloading the models.

Observed specialist result: whole processes16.021/35.046s, peak RSS1950.020/
2243.730MiB on the main host. Unbiased output replaces some Russian words with
English nonsense. Context initially completed names inside longer words; a
bounded repair now requires a right delimiter or virtual EOS before completion.
`specialist_pair.py replay --receipt ORIGINAL_JSON --output NEW_JSON` uses only
retained scores with this repair, not another acoustic pass. Score2.5/beam32 stay
fixed, although the added delimiter is another credited token. The repaired
outputs still insert incorrect complete names: rejected, not a Deck candidate.
Replay took2.272/6.939s, RSS91.605/181.094MiB, no guard stops. Numeric head and
word-boundary constraints hold; accuracy remains unresolved.

The initial specialist loader failure occurred before any model forward because
the old English checkpoint omitted the training-only `masked_spec_embed`.
Inference now disables SpecAugment and does not construct this absent parameter;
all checkpoint parameters still load strictly and retain exact values. Failed
receipts are kept separately; no random replacement weights were used.

## LM inside the specialist pair graph

`specialist_lm.py pilot MANIFEST` scores retained specialist token prefixes with
the existing pinned ruGPT model. Its manifest follows `ctc_lm.py` but each
receipt is a completed specialist-pair cell and context receipt is the matching
whole-word replay. There is no acoustic model or waveform input. The optional
scorer integration keeps head-specific blank/nonblank masses separate from LM
and context credit. Beam32/prebeam64, LM alpha0.3, completed-word bonus1 and
context0/2.5 are fixed, not a score sweep. Provisional full prefixes are scored
before pruning; EOS settles the final sequence. The prebeam is approximate.

For LM scoring only, English uppercase acoustic pieces are mapped to lowercase
and delimiters to spaces. Raw output preserves the publisher's pieces and
numerical origins. The actual LM-scored string and a direct teacher-forced
probability consistency observation are recorded. Two-thread CPU guards and
KV target are reused from the earlier CTC LM runner. This is a new combination
of existing acoustic scores, not a claim that a text model fixes recognition.

Observed specialist-LM result: short process242.343s/RSS1682.211MiB, but
context repeats false names. Long no-context decode finished527.934s; the second
variant hit the shared600s limit, with2532.941MiB peak RSS. Three completed best
LM sums agree with direct teacher forcing within2.5e-5. The failed long cell and
its completed first variant remain separate evidence; no rerun or timeout raise.

## Model-derived language timing and native acoustic clocks

`proposal_support.py --receipt PAIR_JSON --proposals WHISPER_JSON --output NEW_JSON`
scores all retained N-best candidates against head-specific CTC paths and records
Viterbi label frames. Normalization is only for scoring; unsupported words fail
rather than disappear. This finite-candidate diagnostic is NOT an open-vocabulary
recognizer or a hard RU/EN constraint on Whisper. Acoustic ranking rejected a
repeated clause but still preferred a damaged short name.

`guided_pair.py --receipt PAIR_JSON --support SUPPORT_JSON --output NEW_JSON`
uses the fixed context-rank1 candidate only to derive head timing. Open beam32
still chooses the actual token sequence, with whole-word context0/2.5. It is not
trained frame-LID. Long-recording names improved without false extra names, but
Russian remained poor. Short names still failed; no deployment recommendation.

`giga_component.py pilot MANIFEST` observes the pinned Russian-only GigaAM-v3
CTC export (`csukuangfj/sherpa-onnx-nemo-ctc-giga-am-v3-russian-2025-12-16`,
revision32a4c7cc81809bd132e2d935ab99e9e6ab47fbec). The manifest uses the existing
MMS runner shape: model directory, new results directory, recordings with id/wav/
sha256. Task-local torchaudio2.5.1+cpu implements the official320sample Hann/FFT,
160sample hop,64HTKmel,power2,centerFalse/log-clamp frontend. No appended audio,
VAD or resampling. Native34-class log probabilities are retained immediately.
The published example's unspecified KNF window is not used. Russian improved;
English did not. Whole processes3.505/4.006s, peak828.363/841.980MiB on the main
host; these are not Deck measurements or full bilingual-pipeline times.

`native_clock_pair.py --russian GIGA_JSON --english PAIR_JSON --guidance GUIDED_JSON
--russian-model MODEL_DIRECTORY --output NEW_JSON` reuses these scores and the
old English head. One beam traverses routed native events:40ms RU and20ms EN,
without probability interpolation/repetition or independently decoded regions.
It selects rows using the fixed earlier auxiliary schedule; original whole
arrays stay intact. At each switch an actually scored delimiter must close the
prior word before pruning. The first attempt lost all closed paths because the
condition came after beam pruning; the repaired attempt preserves that acceptance
condition before pruning, with no fabricated spaces or changed switch times.

Native-clock output uses trained EN0–31/RU32–65 provenance (specials/blank cannot
emit), open characters and context0/2.5. Repaired decoder-only times2.411/8.211s,
RSS179.289/262.035MiB. Long names and ordinary Russian improved, but short names
and words near switches still fail. Nominal convolution centers are not calibrated
lexical emission times; the old Golos alignment may discard new-head speech.
A direct observation of saved logits confirms that fixed old-head switches discard
complete Russian emission runs at two long-recording boundaries and keep only
part of a transliterated name in the short clip. No encoder or decoder was rerun
for this observation. Returned N-best IDs, within-word head continuity and score
sums satisfy implemented constraints, not recognition accuracy. A future joint
alignment must use the current heads; hand-moving switches is not a quality fix.
No new Deck run, full-pipeline latency claim, gold/WER claim or production switch.

## Current-head alignment and fixed-path diagnosis

`current_head_alignment.py --russian GIGA_JSON --english PAIR_JSON --proposals
WHISPER_JSON --russian-model MODEL_DIRECTORY --output NEW_JSON` replaces the old
Golos switch schedule with an asynchronous forced alignment on the current native
heads. The fixed existing context-rank1 proposal only guides alignment; the final
open decoder receives selected head/native-frame events, never proposal words.
Inactive-head events carry state without emission cost, and head changes occur
only at supplied word boundaries, including an optional new-head blank state.
Duration weights RU2/EN1 come from native40/20ms strides, not fitted coefficients.
This is a composite Viterbi objective, not calibrated language confidence.

Actual processes2.500/8.560s, RSS177.141/247.125MiB, with alignment0.076/0.379s.
Backtrace sums agree within2.85e-14; numeric and word-boundary constraints hold.
Some lost Russian boundary words returned, but the long acronym was lost and the
short name still failed. This is conflicting partial evidence, not a solution.

`native_path_support.py --result RESULT_JSON --alignment ALIGNMENT_JSON --russian
GIGA_JSON --english PAIR_JSON --output NEW_JSON` computes unpruned fixed-path CTC
mass on those exact events. It does not rerun an open decoder or emit a new
transcript. Proposal paths with/without explicit final delimiter are reported
separately because displayed text strips that delimiter. Identical context credit
is applied after exact path scoring. In both clips a known erroneous output still
beats the auxiliary proposal, despite measurable beam pruning loss. Thus merely
increasing beam cannot make the proposal optimal under the current objective;
no beam/bonus grid or manual output substitution follows from this diagnostic.

## English FastConformer and mixed transducer follow-up

The separate English-only hybrid is
[`nvidia/stt_en_fastconformer_hybrid_large_pc`](https://huggingface.co/nvidia/stt_en_fastconformer_hybrid_large_pc),
revision `e60371c84e0d84d12d3ce5c94732022c8388b7ea`, CC-BY-4.0.
This is **not** the multilingual checkpoint above. The FP32 CTC export is
[`OpenVoiceOS/stt_en_fastconformer_hybrid_large_pc_onnx`](https://huggingface.co/OpenVoiceOS/stt_en_fastconformer_hybrid_large_pc_onnx),
revision `af823bde696b1a505695b0b764e9f051acc4ce9e`.

- `english_fc.py prepare --model MODEL_DIR` checks pinned archive/export digests,
  all exported learned tensors (including 17 folded Conv/BN pairs), original
  tokenizer IDs and the CTC head. It retains original Hann/mel buffers. This is
  parameter correspondence, not a proof of full graph equivalence.
- `english_fc.py pilot MANIFEST` runs one intact original recording through the
  English CTC component and retains every native 80 ms score row. The manifest
  uses `model`, `results_directory`, and `recordings[{id,wav,sha256}]`. No VAD,
  appended waveform, resampling or English character-only vocabulary reduction.
- `subword_pair.py --russian GIGA_JSON --english ENGLISH_JSON --proposals
  WHISPER_JSON --russian-model GIGA_DIR --english-model ENGLISH_DIR --output
  NEW_JSON` combines original English SentencePiece IDs with Russian character
  IDs. English offset 0, unknown 0, blank 1024; Russian offset 1025, local space 0
  and blank 33. Only trained non-special IDs emit. Word-start pieces and Russian
  spaces supply actual language-switch boundaries. A context-only marker requires
  whole-word hint completion; it never appears as an output token.
- Auxiliary alignment uses the fixed retained Whisper context-rank1 proposal,
  native EN80/RU40 ms events and duration weights EN2/RU1. These composite scores
  are not calibrated language probabilities. Final beam32 receives only selected
  head/frame events, not auxiliary words; every current-head ID is considered.
  Context 0/2.5 is fixed. Boundary-credit and tokenization changes mean hint totals
  are not numerically comparable with the earlier character-head bonus.
- `english_rnnt.py pilot MANIFEST` uses the original trained English predictor and
  joint network, without another acoustic pass. All 1025 saved CTC log probabilities
  identify 512 encoder coordinates through the original centered projection.
  Observed rank512, condition57.5720, maximum reprojection error below5.65e-6.
  These recovered FP32 activations are numerically close, not bit-identical.
  This diagnostic uses beam4, maximum10 symbols/frame, context0/1.5. Manifest
  shape matches `rnnt_fp32.py`, with the English CTC receipt and model directory.
- `mixed_transducer.py pilot MANIFEST` runs one open beam over Russian CTC and
  English RNNT events. English predictor state persists across Russian events;
  no per-region decoders or transcript splicing. Beam4/max10/context0/1.5. The
  manifest's `receipt` is the recovered English encoder JSON and `context_receipt`
  is the saved subword alignment. The fixed routing remains CTC-derived: it may
  truncate RNNT emissions whose timing differs. Counts of paths reaching the
  symbol cap are exploration counts, not evidence that the winning path hits it.

Observed host results, short/long respectively:

| Stage | Whole process, seconds | Peak RSS, MiB | Observed limit |
| --- | ---: | ---: | --- |
| New English acoustic component | 4.006 / 4.506 | 1170.605 / 1355.703 | English-only greedy output inadequate |
| GigaAM + English subword CTC, alignment + both contexts | 13.817 / 16.200 | 280.551 / 297.602 | One short name recovered; main names fail |
| English RNNT diagnostic, recovery + both contexts | 12.017 / 30.037 | 1127.770 / 1126.895 | Long acronym recovered; principal name fails |
| GigaAM CTC + English RNNT, both contexts | 21.028 / 18.025 | 701.141 / 765.434 | Names and some boundary words still fail |

English acoustic forward alone took0.150/0.550s. The decoder rows are **not**
end-to-end pipeline latency or Deck measurements. Each stage is sequential and
separate; peak RSS values must not be added into a claimed concurrent peak.
No guard stop or sampled swap growth occurred. These are consumed configurations,
not successful solutions. No new Deck run or production switch followed.
Private raw transcripts remain outside Git; no human reference/WER is available.

`mixed_path_support.py --root PRIVATE_ALTERNATIVES_DIR --clip short|long
--output NEW_JSON` computes exact fixed-path mixed mass for the auxiliary and both
already-emitted best paths, plus an approximate zero-encoder internal-language
prior from the original RNNT predictor/joint. It is not a new recognizer. Exact
mass is identical with and without the10-symbol cap on all six paths. Known
incorrect paths remain ahead of the auxiliary by28.91–30.14 score units in the
short clip and52.12–53.84 in the long clip under the same context. Beam loss exists,
but expanding beam cannot overturn those known path scores. Removing one full
unit of the approximate internal prior still leaves the long auxiliary behind;
no tuned subtraction/bonus grid is justified.

`transducer_alignment.py pilot MANIFEST` then replaced CTC-derived routing with
native English RNNT/Russian CTC Viterbi on all retained native frames. Same
manifest as the mixed decoder, but a fresh result directory is mandatory. Fixed
proposal labels determine only auxiliary alignment; the final open search sees
only head/frame events and keeps beam4/max10/context0,1.5. Complete label coverage
and backtrace sums agree below2.85e-14. The short route gained two English frames,
the long route one. Whole processes22.530/21.528s, RSS701.316/781.375MiB;
alignment0.282/1.895s. Names and omissions remained: changing this routing alone
was not sufficient. This is another consumed negative method, not an unfinished
alignment implementation or permission to rerun the same encoder.

## Larger English Parakeet CTC component

`parakeet_english.py prepare --model MODEL_DIR` and `parakeet_english.py pilot
MANIFEST` reuse the whole-recording English component runner for the distinct
[`nvidia/parakeet-ctc-0.6b`](https://huggingface.co/nvidia/parakeet-ctc-0.6b),
revision `ad09ba1cc62743fbc9814de5d2016fca9096485a` (CC-BY-4.0).
This English-only CTC model is not production multilingual Parakeet TDT0.6Bv3.
Its card reports64K hours of English training; that is not a claim of Russian
accent or code-switch quality. Direct NeMo export:
[`istupakov/parakeet-ctc-0.6b-onnx`](https://huggingface.co/istupakov/parakeet-ctc-0.6b-onnx),
revision `658f956396c5a6e41f23ed50838bdb7d1d1b6056`.

Preparation verifies the original archive, FP32 ONNX graph and external tensor
file independently; external arrays are memory-mapped for parameter matching.
The native architecture has24 layers, width1024 and80ms output stride. The
published1024-token vocabulary uses lowercase English. Auxiliary English labels
and hint tokenization follow that convention, explicitly recorded in the prepared
receipt; final recognized text is not case-rewritten or replaced. The existing
`subword_pair.py` consumes the new receipt plus retained GigaAM scores; its
beam32/context0,2.5, native event clocks and trained-head offsets are unchanged.
All854 exported initializers were accounted against the original checkpoint,
including24 folded Conv/BN pairs. Original Hann/mel buffers matched the prior
English component exactly. Full graph equivalence is still not claimed.

One new English acoustic pass per clip completed in8.513/10.013s, with forward
itself0.784/2.577s, RSS2633.414/2676.320MiB. These are host observations, not Deck
measurements. Joint auxiliary alignment plus open beam took12.160/14.653s,
RSS314.328/279.398MiB. Both short names and the first long name were recovered with
context; the long acronym and some Russian words remained missing.

A retained-score observation found a concrete hard-routing conflict: an available
English acronym-prefix emission at5.12s was excluded because the forced Russian
auxiliary words occupied that interval. `phrase_guidance.py` accepts the same
arguments as `subword_pair.py`, but aligns only ordered contiguous English runs
from the same fixed auxiliary proposal. Its CTC trellis allows wildcard gaps,
scored by the per-frame maximum over the complete trained English distribution.
It does not force Russian auxiliary text. Native80ms frame cells determine the
routing intervals; no manual time shifts or waveform cuts. The final unchanged
open beam sees only head/frame events, not phrase words.

Phrase guidance completed in10.359/13.453s, RSS284.320/302.301MiB. All four target
names across the two recordings were recovered with context, but duplicate
Russian fragments and the original Russian omission remained. This is a partial
improvement, not a full ASR solution or ground-truth language detector.

`subword_lm.py pilot MANIFEST` reuses those frozen events and native scores with
the previously pinned probability-only ruGPT scorer: beam32/prebeam64, alpha0.3,
completed-word bonus1, context2.5, one variant per recording,600s/4096MiB guard.
The manifest uses `root`, the LM `model` directory, `results_directory`, and
`recordings[{id,receipt,context_receipt}]` pointing to the phrase-guided result
and its alignment. LM scores full provisional prefixes before beam pruning and
EOS once at completion; it has no generate call or transcript rewrite. Actual
best-path cached scores are checked against teacher forcing. No old acoustic
baseline, language-routing or encoder pass is repeated.

That fixed LM variant completed in83.613/357.471s whole-process time,
RSS1544.063/2335.984MiB; cached/direct best-path log probabilities agreed within
2.50e-5. It removed the short duplicate fragment while preserving names, but
worsened Russian words in the long recording. Names alone are not the acceptance
criterion. The long latency is unsuitable for dictation, so no Deck deployment,
LM weight grid or production switch followed. The256MiB KV setting is a retention
target; transient cache peaks were258.35/260.01MiB before eviction. No guard stop
or sampled swap growth occurred.

## Russian RNNT and native word-state repair

`giga_transducer.py prepare --model MODEL_DIR` verifies the separate
[GigaAM-v3 RNNT checkpoint](https://huggingface.co/ai-sage/GigaAM-v3/tree/c7f128b8accdd9624df905e5c2d7b7a48c27c0d8)
and [pinned ONNX export](https://huggingface.co/csukuangfj/sherpa-onnx-nemo-transducer-giga-am-v3-russian-2025-12-16/tree/0424d62637b37d8b7b1eb0f75a04d78dec55fdcc).
This is not the earlier Russian CTC checkpoint. It has a40ms native encoder,
33 Russian characters plus blank33, one320-wide LSTM predictor and a34-class
joint. The encoder is int8; predictor and joint are FP32. Preparation matched370
unquantized encoder tensors and178 quantized tensors within0.500004 quantization
steps of original weights, plus exact predictor/joint parameters after required
ONNX LSTM gate and bias permutation. This does not prove full operator parity.

Runtime-generated frontend buffers differed from the original checkpoint by up
to0.0019513. Preparation preserves the actual original window/mel buffers and
inference loads those bytes, instead of silently accepting the difference.
`giga_transducer.py pilot MANIFEST` takes the same `model`, `results_directory`,
and `recordings[{id,wav,sha256}]` component manifest as other whole-audio runners.
One intact-audio pass per clip completed in3.504/4.004s, RSS837.945/852.465MiB.
Native encoder arrays are retained. Original greedy max10-symbol semantics are
used; publisher-example appended silence and single-symbol limits are not.

`russian_mixed.py pilot MANIFEST` uses retained Russian RNNT encodings and English
Parakeet CTC scores in the existing shared beam, with no acoustic rerun. Its
manifest uses the task `root`, Russian RNNT `model`, `results_directory` and
`recordings[{id,receipt,context_receipt}]`: the receipt is the Russian component,
and context_receipt is the frozen English phrase-guided alignment. English IDs
and global Russian offset1025 remain unchanged. The Russian predictor consumes
only its own real emitted IDs and persists through English events. This initial
configuration truncated output because the global word rule demanded a second
Russian space after an English insertion, although the native Russian predictor
had already emitted its own word-ending space.

`russian_boundary.py pilot MANIFEST` repairs that state mismatch. An RU→EN switch
requires an actually emitted Russian word-closing token; returning EN→RU can
continue from that still-closed native Russian state without another acoustic
space. No fake token is sent to the predictor. A context-only boundary marker
closes a hint at the accepted switch. Literal `raw_piece_text`, original token
IDs and `raw_text` are retained; `postprocessed_text` may add a separator only
where two trained-head words would otherwise touch. Inserted positions are
explicit in `formatting_only_inserted_space_before_token_indices`. This is
formatting, not a claim of no postprocessing or semantic transcript repair.

The completed two-sided correction recovered all four technical names across
the two recordings, retained the Russian continuation and restored a previously
missing Russian phrase. It is the first substantially coherent paired-head
result here. Residual Russian spelling errors remain, and no human gold/WER or
new-recording generalization evidence exists. Beam4, max10 and context0/2.5 were
unchanged; the LM scorer is not used. Final process time, including both decoder
variants, was6.008/28.542s, RSS178.309/386.285MiB; the context search alone took
3.702/15.072s. These timings exclude encoders and auxiliary Whisper inference.
No whole-pipeline or Deck measurement is claimed. No production switch followed.

## Compact English export and sequential pipeline

`parakeet_int8.py prepare --model INT8_DIR --parent VERIFIED_FP32_DIR`
checks the published compact export from the same pinned repository revision.
All854 parent initializers were accounted:295 quantized tensors differ by at
most0.500004 scale units; remaining tensors match exactly. It reuses original
frontend/tokenizer bytes, rather than inventing a compact vocabulary. The one
whole-audio int8 component pass used1883.539/1914.273MiB RSS on the host.

Initial mixed beam4 pruning lost the main name in both clips. Recomputing
auxiliary timing from int8 scores did not fix it. Exact complete English-path
scores showed the known better contextual path was being pruned early. The
repair retains the existing native CTC beam32 during English events while
keeping Russian RNNT beam4/max10. No bonus increase or width sweep was used.
`compact_mixed.py` selects this repaired configuration; `compact_guidance.py`
can derive native timing from the retained int8 scores. All four names and the
same Russian text as the prior FP32 candidate returned with context2.5.
Context-only search took6.851/11.869s on the host, excluding acoustic models.

`paired_pipeline.py pilot MANIFEST` runs separate sequential child processes:
whole-audio auxiliary Whisper, whole-audio English CTC, whole-audio Russian RNNT,
then current-score phrase timing and one shared constrained search. It never
splices completed model transcripts. The auxiliary proposal only determines
English phrase timing. Each model process exits before the next loads; prior
stage receipts and arrays remain on disk. NumPy frontends load the original
stored buffers. Their maximum differences from the Torch formulas on the two
whole recordings were below0.000060 for English and0.000299 for Russian, not
bit identity.

The manifest contains `source_commit`, `source_files` (filename to SHA256),
`whisper_python`, `acoustic_python`, `whisper_model`, `english_model`,
`russian_model`, `results_directory`, `rss_mib`, and
`recordings[{id,wav,sha256}]`. The English runtime expects `runtime.onnx` plus
external `runtime.weights`, with hashes in `prepared.json.runtime_external_files`.
Storage conversion preserved all1522 compact initializer arrays byte-for-byte;
no arithmetic or quantization change is involved. Host load-only peak was
630.859MiB without Torch, not a full-inference or Deck memory claim.

Pipeline guards cover each native child process: requested RSS cap, available
memory floor2048MiB, swap growth256MiB,85°C and600s per recording. These are
agent-selected method limits, not a user deadline. Every stage saves its own
status, provenance, peak RSS and supervisor samples; a failed/unknown stage
must not be repeated automatically. Only one context variant is used in the
full pipeline. Its total time includes auxiliary inference and cold model
loads, unlike the preceding decoder-only timings.

The isolated Deck pipeline completed both recordings in22.938/41.335s with
peak stage RSS962.027/1044.621MiB. Minimum available memory was2273.082/2173.242MiB,
above the2048MiB reserve; maximum observed temperature67/70°C. Sampled swap growth
was0.109375MiB for the short recording and0 for the long one. Sequential stage
peaks are not summed. Production services remained active with their original
PIDs. The stricter1280MiB process cap was selected before execution after a1400MiB
preflight did not fit the current available-memory budget; no acoustic pass
occurred under the rejected preflight.

The short result retained both names and the Russian continuation. The long
result failed the principal English name and omitted an intervening Russian
phrase, despite host success. The Deck uses ONNX Runtime1.31 rather than the
host's1.20.1; retained logits and derived timing differ. The cause of numerical
differences is not established. Do not describe host and Deck output as parity.

Exact scoring of two actually observed paths on the Deck's own arrays showed
the prior good host path beats the erroneous Deck path by10.183945 score units
with the existing hints. Max10 RNNT emissions changed these exact masses by
less than3.4e-9 relative to uncapped paths. Search loss is therefore established,
not a claim that the target path is acoustically impossible. A passive trace
located loss of the compatible English prefix at rank38 versus CTC beam32.
Neither applying native word-switch acceptance before pruning nor reserving
representatives of distinct context states within the same32-path budget fixed
the long output. Their negative receipts remain separate. Context banking is
optional (`context_banks` in the pipeline manifest), not a recommended fix.

For causal decoder-only observations, `retained_inputs_directory` in the manifest
reuses saved auxiliary/English/Russian receipts and arrays and runs only `final`.
Such results are not full-pipeline latency measurements. `deck_path_mass.py` and
`trace_deck_pruning.py` inspect observed paths without fabricating target words;
the latter verifies that its callback leaves the winner unchanged.

### State-recombined search: latest partial result

`state_transducer.py` replaces competition between entire English prefixes with
sufficient-state recombination: native Russian predictor history, last emitted
trained token, CTC blank status, and context-automaton state. All reachable
English states remain eligible for four retained native Russian histories. This
is a different search budget, not the old32-path beam made implicitly wider.
It reached8364 simultaneous states on each recording without changing context2.5,
model scores, routing or the open vocabulary. The design follows the token-passing
principle of [Flashlight's lexicon-free decoder](https://github.com/flashlight/text/blob/main/flashlight/lib/text/decoder/LexiconFreeDecoder.cpp),
with the separate native Russian predictor retained by our mixed decoder.

Set `search_method` in the pipeline manifest:

- `sufficient-state-viterbi`: maximum single acoustic path; never sum different
  emitted texts. This recovered all four names on Deck but omitted a Russian
  phrase. Exact saved-path scoring showed that omission marginally wins under
  Viterbi, while the complete phrase wins under transcript-forward logsum.
- `sufficient-state-forward`: log-add alignment paths only when their complete
  emitted token tuples are identical. Different texts sharing the same sufficient
  state compete by score; their probability masses are never summed. This is
  approximate retained forward mass, not an exact transcript posterior.
- Omitted: original prefix-beam implementation, for preserved compatibility.

The forward-state method recovered all four names and the missing Russian phrase
on the Deck's retained arrays. The best displayed token strings match the prior
successful host int8 result. Residual Russian error remains. Search took5.314/13.112s;
supervised final-only stage time was5.909/13.741s, child-reported peak RSS123.703/132.387MiB.
All guards passed. These are decoder-only measurements, not the full chain.
The prior full-pipeline22.938/41.335s must not be reassigned to this later method.

`deck_path_mass.py --viterbi` selects exact max-path diagnostics; without the flag
it uses exact fixed-transcript logsum. These diagnostics never supply target
words to final recognition. Source and all failed variants remain pinned in the
private receipts. No acoustic pass, auxiliary-model repeat, stronger hint or
production switch was used for the state-method repairs.

This is a promising isolated prototype, not a production recommendation. Latest
end-to-end latency, residual Russian accuracy and generalization beyond the two
retained recordings remain unverified. Production services are unchanged.

## Collected-speech evaluation

`corpus_inventory.py CORPUS OUTPUT` reads only TAR metadata from the rolling
speech store. It distinguishes STT from TTS/journal records and retains reference
and request-policy provenance privately. `corpus_eval.py select INVENTORY OUTPUT`
freezes a small chronology-spread sample: ten saved-text Latin examples, ten
technical-name proxies, and ten other Russian examples. These are metadata
strata, not verified language labels. It excludes development-audio hashes,
duplicates, dictionary opt-outs and unsupported input lengths/formats.

`corpus_eval.py prepare SELECTION CORPUS ROOT` copies exact selected WAV bytes and
metadata into an isolated root, verifies SHA256 and records missing/invalid
sources without replacement. `corpus_eval.py run MANIFEST` invokes one full
`paired_pipeline.py` process per recording. Ordinary per-record failure remains
in the results while untouched records continue. A resource guard or unknown
outcome stops the remaining work; consumed records must not be resubmitted.
Optional `capacity_wait_seconds` waits before dispatch only, without lowering
the memory reserve. Resume by creating a new manifest containing only the
explicitly untouched IDs and a new results directory.

The full pipeline now handles an auxiliary proposal with no English phrase by
retaining all Russian native frames. It does not force the auxiliary Russian
words. Impossible English alignments and unrepresentable auxiliary words remain
explicit failures, not opportunities to tune hints against the sample.

`corpus_report.py ROOT` joins the frozen selection, preparation receipts and
`results-v*` directories into a private comparison JSON and self-contained HTML.
It reports every selected item, full-chain timings, measured resources and
normalized-text disagreement. Saved production and auxiliary outputs are not
human gold; no WER or accuracy claim is made. Do not commit any private corpus
manifest, WAV, transcript or generated report to this repository.

Observed first frozen sample:30 selected, one source expired before copying,
29 attempted once,21 completed transcripts and8 failures. Four failures were
impossible auxiliary phrase alignment, three unrepresentable auxiliary words,
one a Whisper RSS guard. The last untouched record completed separately under
the same limits; no consumed failure was retried. Orchestration-only recovery
added up to120s capacity waiting before untouched records. Model/search/hints
remained fixed throughout.

Among21 completed outputs, normalized agreement with archived production raw
text was2 equal,11 small differences and8 substantial differences. These are
not correctness counts. Several completed outputs also show severe language
routing distortion. Median successful cold full-chain time was19.648s, range
12.017–37.173s; aggregate409.203s processing /135.848s audio =3.012x real time.
Minimum available memory remained2194.684MiB, above the2048MiB reserve; maximum
sampled temperature76C, no sampled swap growth. The failed guard reached
1160.789MiB sampled RSS against the1100MiB cap and was terminated.

The two-development-clip success did not generalize sufficiently. Do not deploy
this candidate based on that result. Auxiliary repetition/unsupported-word
handling and hard routing remain concrete weaknesses; this evaluation did not
retune them to improve the held-out score.

## Standalone GigaAM context experiment

`giga_context_eval.py run MANIFEST` evaluates the pinned original GigaAM
Multilingual Large CTC checkpoint on whole PCM16 mono16k recordings. It verifies
source/config/weight hashes, loads all original tensors strictly, and retains
native71-way log probabilities after one acoustic pass per recording. The model
remains loaded between recordings. Three outputs share those probabilities:
native greedy, open CTC beam32 without context, and beam32 with the four existing
name hints at2.5 per character. No Whisper routing, alphabet masking, lexical
replacement, waveform segmentation/padding or weight training is used.

The full shared multilingual vocabulary remains open. Context paths are
character substrings, not enforced word boundaries; incomplete credit is
refunded and overlapping phrases cannot double-credit output positions. The
beam/top32 acoustic pruning remains approximate. This does not satisfy the
original requirement for separately trained RU/EN-only heads.

`giga_context_report.py ROOT --results results-v3` combines private results with
the preceding corpus references into private JSON/HTML. Never embed literal
private transcript examples in this generator or commit generated corpus files.
The repeated29-record sample is exploratory, not a new blind holdout.

Observed frozen comparison:29/29 completed, but all greedy/beam/context outputs
contained no Latin characters. Context changed0/29 best beam outputs. The
median utterance Latin-symbol share of nonblank probability mass was0.0014%,
maximum0.0157%; this is a symbol-mass diagnostic, not calibrated language ID.
The run took146.642s including loading and both beam variants on harness-test,
CPU FP32/Torch2.5.1/two threads, **not Deck**. Median acoustic time1.471s,
median context decode1.075s; sampled process peak3691.234MiB. Original FP32
weights alone exceed the observed Deck budget after its2048MiB reserve.

Actual fine-tuning is separate from context decoding. The
[official training tools](https://github.com/salute-developers/GigaAM/tree/main/train_utils)
support CTC/RNNT fine-tuning and new vocabulary/heads on SSL backbones. Improving
mixed-language behavior requires appropriately labeled RU/EN examples and a
separate evaluation split. No training was launched and the collected corpus
still has no human-verified transcript references.

## Experimental <=1B editors and EmbeddingGemma 2

The separate [mini-editor contract](../../docs/specs/asr-mini-editor.md) covers
`mini_editor.py`, `embedding_selector.py` and `mini_editor_report.py`. These are
private-artifact evaluation tools, not a production postprocessor. They preserve
raw ASR and do not satisfy or replace the trained RU/EN acoustic-head constraint.
The mini-editor runner starts a task-owned loopback llama.cpp server temporarily
and terminates it after its bounded batch; it does not restart existing services.

With the pinned assets and frozen suite described in that contract:

```sh
python mini_editor.py qwen3 --root /private/mini-editor \
  --suite corpus-suite.json --result-name results-qwen3-corpus --modes rank
python embedding_selector.py --root /private/mini-editor --base /private/audio-root
python mini_editor_report.py /private/mini-editor
```

Initial evaluation completed91 generation requests across two Q8_0 models and
four batches, plus10 text-similarity controls and2 whole-audio embedding passes.
Qwen2.5/Qwen3 free editing matched synthetic normalized references3/10 and5/10;
index selection matched9/10 and10/10, but Qwen3's chosen text changed in14/20
real-corpus pairs when candidate order alone was reversed. Original-order
selection chose displayed index0 in20/20. These are not human-gold ASR scores.

EmbeddingGemma2 revision914f7f89142e33e77833254d9c9b90c3cef7303b uses native
Transformers5.19.0/Torch2.8.0 CPU in a separate environment, FP32 text+audio with
vision disabled. Mask-aware mean pooling and768D L2-normalized embeddings follow
the publisher. Audio padding/truncation is disabled outside the native STFT.
On the long development clip a negation-deleted probe outranked unchanged ASR;
on the short clip a candidate with an extra trailing conjunction ranked first.
Its cosine score is not word correctness or calibrated acoustic confidence.
Both per-clip outputs/vectors survived, but the original overall summary failed
on a set-valued loading-info field; full-run RSS/time were not recovered or
invented. The serialization fix is for future calls, not a repeated inference.
Neither free editing, index generation nor embedding-only selection is approved
for automatic transcript replacement by these observations.

### Independent conditional candidate likelihood

`candidate_likelihood.cpp` is a small driver linked to the unmodified pinned
b11429 libllama C API. `candidate_likelihood.py` freezes exact Jinja-rendered
prompts and candidate text, supervises resource limits and retains every target
token/log probability. Build against the version-matched public headers and
libraries, placing the binary at `ROOT/likelihood-native/candidate-likelihood-sequential`.
It uses Qwen3 Q8_0, CPU2, FP16 KV, context4096, no weight repacking or generation.

```sh
python candidate_likelihood.py prepare /private/mini-editor
python candidate_likelihood.py run /private/mini-editor
python mini_editor_report.py /private/mini-editor --filename mini-editor-round10.html
```

Each candidate is scored independently as an assistant continuation conditioned
on original ASR. Primary score is mean full-vocabulary log probability including
end-of-turn. KV is cleared per candidate; equal different-text maxima are kept
explicit. No candidate list is fed to the model. This remains conditional text
likelihood, not acoustic confidence.

The initial chunk64/chunk1 parity check failed with0.0320915 maximum per-token
logprob difference against the fixed0.001 tolerance. Disabling CPU repacking did
not change it; both launches stopped before any real candidate. The replacement
method uses only single-token decoding. Its narrower causal-prefix check passed
exactly on7 shared target tokens; cross-runtime numerical parity is not claimed.
All35 frozen cases/110 unique candidate paths then completed:13/13 synthetic
reference matches,19/20 collected-ASR texts unchanged, both development texts
unchanged including a residual error. Cached-score selection was invariant in
594 permutations with zero additional model calls. No acoustic improvement is
established without human references.

Host CPU wall431.342s, sampled peakRSS1110.695MiB; median total candidate-scoring
time per corpus recording12.587s. This is not Deck latency and does not justify
production promotion. `likelihood_report.py` adds the complete private scores
and observed changes to the existing report without publishing transcripts.

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
