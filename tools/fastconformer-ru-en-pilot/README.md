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
