# Bounded private Qwen3-ASR pilot

Compare five retained Russian speech clips and two synthetic negative controls,
without switching production STT or treating old ASR text as a human reference.

## Preparation

Python 3 standard library only. The current preparation and baseline adapters
use the existing `steamdeck` SSH alias and its established voice-corpus/loopback
Parakeet endpoints. They are local operational adapters, not a hosted service.

```sh
python3 prepare.py PRIVATE_ROOT --complaint-id PRIVATE_ID_1 --complaint-id PRIVATE_ID_2
python3 baseline.py PRIVATE_ROOT
python3 run.py PRIVATE_ROOT
python3 collect.py PRIVATE_ROOT
python3 -m unittest discover -s . -p test_pilot.py -v
```

Preparation freezes a SHA manifest before inference: two supplied complaint IDs,
the latest two eligible 18–35-second natural utterances, one eligible technical
7–15-second clip, and deterministic one-second silence/weak-noise controls.
Total real speech must not exceed 120 seconds. IDs, WAVs, metadata, outputs and
model assets must stay in the private root, outside Git.

`baseline.py` verifies every WAV hash and sends identical bytes directly to the
already-running Parakeet API, not the gateway that ingests synthetic telemetry.
It preserves completed output and errors even when a request fails.

`run.py` expects a prebuilt reviewed `native-source/qwen_asr` from
[antirez/qwen-asr](https://github.com/antirez/qwen-asr), original pinned
Qwen3-ASR-1.7B assets in `model/`, a verified ten-file `model-receipt.json`, and
private BLAS libraries under `blas/root/`. Build and download are intentionally
not automatic. The runner records the actual source/model revisions, model size,
WAV hashes, exit code, transcript, wall time and observed peak RSS.

The candidate receives only WAV audio and explicit Russian: no initial prompt,
previous transcript, past-text context, or silence compaction. Each recording is
one full-audio request. Controls run first, with one process per clip. Two CPU
threads, nice 19, a 900-second aggregate inference budget and an 8 GB RSS stop
threshold bound this pilot. RSS is sampled every 100 ms, so this is not a hard
OS memory limit and can miss short peaks. Existing result files are not silently
overwritten. Failed inference stops subsequent clips and is not counted as a
successful completed comparison.

## Expanded comparison and private listening page

The user approved testing the presented candidate matrix, not just Qwen. Reuse
the frozen manifest and already-completed baseline/Qwen outputs. Added tooling:

```sh
python3 fetch_matrix.py PUBLIC_MODEL_ID PRIVATE_MODEL_DIRECTORY --pattern '*.gguf'
python3 run_matrix.py PRIVATE_MATRIX_ROOT PRIVATE_CONFIG.json PRIVATE_MANIFEST.json
python3 build_page.py PRIVATE_PILOT_ROOT PRIVATE_MATRIX_ROOT PRIVATE_OUTPUT.html
```

`fetch_matrix.py` pins the first public API response and verifies artifact sizes
and LFS SHA-256 before reuse. `run_matrix.py` runs each configured native/HF/ONNX
model sequentially under a shared filesystem inference lock. Its 15-minute
budget is intended to start **after** acquiring the lock, not during queue wait.
Every variant has exact provenance, audio hashes and terminal success/error
receipts; output parse/runtime failures stop that branch only. Failed branches
can be retried only with a corrected runtime/config and a distinct result ID,
never by erasing receipts or replacing unknown live work.

`python_decode.py` supports inspected OmniASR HF and T-one ONNX adapters. T-one
uses explicit 16-to-8 kHz resampling and greedy decoding without an external LM;
that is not equivalent to its production beam/LM decoder. OmniASR architecture
support is version-sensitive. Runtime failures must be shown, not replaced by
another model's output.

`page.html` is the committed source template. Generated HTML embeds the exact
original WAVs and actual transcript receipts and **must not enter Git**. Browser
model filters, original audio, preferred-variant votes, optional human correction
and JSON export work locally without external requests. Votes/corrections remain
in browser storage until the user exports them. The standalone generated HTML
also works as a download because audio/data/script/style are embedded.

`browser_check.mjs` accepts an installed Playwright module, browser executable,
exact approved page URL and private receipt path. It checks actual audio decode,
playback preservation on voting, local correction/export, control filters,
mobile overflow and page errors, then closes its task browser. It does not change
browser profiles or production services.

The matrix includes both Qwen sizes, Nemotron 3.5, GigaAM v3 CTC/RNNT, Whisper
stock large/turbo and Russian antony66 fine-tune, Voxtral, Canary, T-one and
OmniASR. Cohere is inapplicable because Russian is not a declared language.
Retained rejected older experiments are history. Community port failures are
not evidence against the original model; preserve them and prefer an established
compatible implementation for a separately recorded retry.

## Interpretation

- Different hosts/runtimes do **not** provide an apples-to-apples latency ranking.
- Native BF16 weight execution is not official Transformers implementation parity.
- Existing ASR text is a hypothesis. Do not calculate accuracy against it as gold.
- Five personal clips can guide a next decision, not establish universal quality.
- Empty text on silence/noise is desirable; fluent invented text is not accuracy.
- Inspect audio and user-corrected words before claiming omissions were fixed.

Research findings and any observed run outcomes belong in
[RESEARCH.md](RESEARCH.md). No production restart, model switch, external private
audio upload or training is performed by these scripts.
