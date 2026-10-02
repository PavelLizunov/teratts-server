# Full retained speech corpus: finite Nemotron trial

**Full runtime pass completed and verified.** All 949 unique WAVs succeeded, covering 951 frozen source records (two exact duplicates), 5671.46 seconds of speech. No failure, unknown dispatch or missing result. New recordings after snapshot are outside this finite experiment. No production STT replacement or training.

This directory backs up source-only tools for the private Model Forge workspace. Snapshot includes empty baseline transcripts and valid failed-upload WAVs if present; excludes synthetic/TTS/dialogue. Manifest/source mappings/audio hashes fixed, private copies immutable. Twenty-seven empty primary transcripts included. Snapshot audio size181.53MB.

Resident NeMo-Speech.cpp0.1.0 CPU loopback decoder loaded pinned official Nemotron3.5Q8 once, no hints. One HTTP worker, one-core-equivalent CPUQuota100%,nice19,idleIO,MemoryMax3GiB,8h cap. Sequential runner yields to observed production demand/lowRAM. Actual supported serve flags only; generic unsupported flags failed before model load and were not silently ignored. Main Parakeet/Vulkan/gateway unchanged.

## Results and limits

Runtime2h23m39 including yielding; request totals7747.672s,RTF1.3661,p50request4.325s,p95request28.6309s on mixed durations. Decoder peak2503778304bytes. This is NOT production Vulkan speed or standardized latency comparison.

Compared with unreviewed recorded Parakeet raw text:120 normalized agreements,442 small,389 substantial disagreements over951source mappings. NOT WER,accuracy or proof of errors. Thirty-three nonemptyprimary->emptycandidate cases all short0.34–2.99s;oneemptyprimary->nonemptycandidate,not proved recovered speech. Silencecontrol empty. No automatic quality promotion or corpus label approval.

Atomic results/dispatch markers support resume without blind retry. Final identity check verified949uniqueSHA/951sampleIDs/allcompleted. Temporary decoder stopped,port10004closed,productionParakeetPID1075558/gateway2014259unchanged/ready. No DSH/TTS restart/cloud calls/providers/weights changes.

## Tests

```sh
python3 -m unittest discover -s tools/nemotron-full/tests -v
```

Seven tests cover exhaustive eligibility/dedup/empty-failure/exclusions,WAV/hash/pathintegrity,immutablemanifest,exactmultipart/nohints,interruptedrequestnotretried,idempotentresultresume,disagreement-notaccuracy. No independent reviewer,fullhumangold,noisy-silence/Vulkan/concurrentcampaign. Private report/results/WAV/weights/OraclestateexcludedfromGit. Full private report is Model Forge docs/nemotron-full-report.md. Do not rerun/replaceproductionfromthisfinishedsnapshotwithoutnewdirecttask.
