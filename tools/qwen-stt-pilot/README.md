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
