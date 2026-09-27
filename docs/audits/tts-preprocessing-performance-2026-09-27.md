# TTS text-preparation performance result

One small algorithmic change is confirmed for the measured malformed-Markdown workload. This is not a neural TTS, Steam Deck, or end-to-end playback speedup.

## Experiment
- Part: speech-preprocessing; one candidate attempted, one kept, zero reverted. Search stopped after the targeted hotspot was removed, not because the ten-attempt budget was exhausted.
- Target: existing DSH Host, Linux x64, Node v22.23.2. Isolated processes; no live inference requests or service changes.
- Evaluator/control commit: ec09c25d5f042ea6512c531208abae95ca45b7cf.
- Candidate: cc7e37ea6bc2d1365fa54eb5c14c48b509642d8e.
- Locked evaluator: evaluators/tts-preprocessing-20260927/manifest.sha256. Corpus, output hashes and policy were committed before candidate implementation. Exact output, browser/Host parity and two injected output-fault checks passed before locking and on both implementations.
- Profiler evidence: evidence/tts-20260927/baseline.cpuprofile. Link/image regexes accounted for 606/179 samples. Diagnostic doubling of unclosed labels from 10k to 20k characters increased time from about 67ms to 269ms.
- Change: after inline-code cleanup, skip both link regex passes when the necessary `](` delimiter is absent. Both Host and client copies changed identically. No parser replacement or dependency added.

## Results
Six contemporaneous pairs per workload, alternating AB/BA, separate Node processes. Two warmups precede each timed pass. Timings cover cleaning and splitting the fixed corpus, not process startup, network, synthesis or playback.

| Corpus | Control median | Candidate median |
| --- | ---: | ---: |
| Search: technical text plus malformed delimiters | 169.379ms | 0.624ms |
| Fresh held-out confirmation: different sizes/text | 321.267ms | 1.026ms |

Search paired median improvement was 168.750ms, above the locked 1.153ms noise threshold (2× paired MAD). Held-out peak RSS was 52,678,656 versus 52,682,752 bytes, within the locked +10% limit. Exact text and chunk hashes matched; injected empty and corrupted output were rejected.

The v2 helper accepted search as KEEP and held-out confirmation as passed; campaign status is completed. Ledger: .dsh/performance-autoresearch/tts-20260927-preprocessing/state.jsonl. Raw paired ordering, samples, quality receipts and hashes are in evidence/tts-20260927/. Reproduce the paired execution with tools/paired_preprocessing_bench.py and a detached control worktree at the evaluator commit. The single-part baseline-to-final confirmation is also the aggregate preprocessing comparison; it is not a whole voice-pipeline benchmark.

## Limits
- Results are dominated by deliberately malformed inputs. Ordinary text was already cheap: earlier diagnostic p50 around 0.22ms for 2408 characters and 0.90ms for 10k characters. No hundreds-fold speedup is claimed for ordinary answers.
- The guard does not remove every possible pathological regex input. Inputs containing `](` still run the existing matcher. This is a targeted mitigation, not complete ReDoS resistance.
- Native model optimization was not attempted on shared production. CT221 currently uses 4 ORT threads, 2 chunk slots, spinning off and first16_then32 windows; no representative isolated native build/profiling environment was established. No quantization, assembly, model changes or waveform-quality claims.
- Self-reviewed only. Actual browser activation and production playback remain unverified because no DSH component was restarted or reloaded.
