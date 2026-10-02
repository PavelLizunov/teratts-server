# Full retained speech corpus: finite Nemotron trial

**WIP runtime checkpoint: run is still executing; do not claim completed comparison.** Source tests pass, full live result pending. This directory is source-only backup for private Model Forge workspace, not a production STT replacement.

Snapshot includes all currently retained real STT WAVs, including empty baseline text and valid failed-upload WAVs; excludes labeled synthetic/TTS/dialogue. Exact SHA deduplicates inference while keeping all source mappings. Frozen manifest/WAVs private and immutable. Initial run captured 951 source records /949uniqueaudio,5671.46seconds,181.53MB;27empty baselines included. New audio after freeze excluded.

Resident NeMo-Speech.cpp0.1.0 CPU loopback decoder loads official pinned Nemotron3.5Q8 once; no hints. Main production Vulkan/Parakeet unchanged. CPUQuota100%,Nice19,idleIO,MemoryMax3GiB,8h cap. Sequential runner yields for observed production connections/recentcorpusactivity/lowRAM; interference cannot be guaranteed zero. Correct supported serve flags differ from some published generic CLI documentation.

Atomic results and dispatch markers permit resume without blind re-inference of unknown started-only calls. Evaluator/model/manifest hashes fixed; summaries report coverage/status/transcript differences, NEVER goldWER. No training/promotion/cloud uploads. Private snapshots/results/rawsourceWAV/weights/keys excluded from Git.

Tests:

```sh
python3 -m unittest discover -s tools/nemotron-full/tests -v
```

Seven tests cover exhaustive selection/dedup/empty-failure/exclusions,WAV integrity,immutablepaths,exact multipart/nohints,resumeunknownnotretried and difference-not-accuracy. Current private run/continuation info is in Model Forge docs/NEMOTRON_FULL_RUN_RESUME.md. Upon runtime completion verify every frozenID,recordfailuresexplicitly and stop only testdecoderunit;never alter existing service.
