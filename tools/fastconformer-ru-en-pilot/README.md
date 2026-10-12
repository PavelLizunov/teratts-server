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

## Limits

Language-branch masking is not semantic language classification. Published
monolingual/multilingual training does not prove continuous code-switch quality.
CPU latency/RSS must be measured on Deck, and no human reference transcript/WER
is available. Feature extraction follows the pinned exporter example rather
than claiming bit-exact Python NeMo preprocessing. No speculative text repair,
ITN or homophone substitution is applied.
