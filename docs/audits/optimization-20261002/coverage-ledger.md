# Audit coverage ledger

## Meaning and boundary

Read-only coordinator inspection of current owned code, combined with executed bounded checks. `read` means source and relevant tests were inspected; it is not a coverage percentage or proof of correctness. `test` refers to actual checks described in check-summary.json. Main snapshot: d937a90778824d1cb564a187f351ff400877cae8. All local/origin branch tips were inventoried; final fetch on 2026-10-03 found main, private and optimization tips unchanged. Audit branch itself contains documents/diagnostic scripts only.

## Main owned executable sources: no unexamined production file

| Files | Inspection and applicable executed checks | Limits |
|---|---|---|
| src/server.rs, remote_primary.rs | Entire source and embedded tests; queue/cancel/join, defaults, auth, primary retry/body/WAV, revision flow | Rust execution unavailable under control-plane guard; primary neural path not executed |
| src/main.rs, tera.rs | Entire source and tests; CLI paths, shape/NaN bounds, style cache, graph options, sampler/vocoder stitching, pool memory | No inference/quality/audio comparison; CUDA/device reachability not checked |
| src/execution_provider.rs, downloader.rs, manifest.rs | Entire source/tests; provider gates, pinned checksum/publication/locks | No downloads, host FS race campaign or GPU |
| src/npy.rs, indexer.rs, rng.rs, wav.rs, chunk.rs | Entire source/tests; input bounds, shape arithmetic, encoding and atomic output | Source-derived CLI diagnostic, not compiled Rust result |
| src/ruaccent.rs, textnorm.rs, num2words.rs | Entire source/tests; tokenizer/offset/output copying, language tag/manual stress/number grammar | Golden model-dependent cases not re-executed |
| src/speechfront.rs, russian_only.rs, lexicon_reload.rs | Entire source/tests; matching order, bounded external converter and cleanup, effective lexicon refresh/revision | No external converter binary or worker invocation |
| dsh-plugin/lib/client.js, index.js, coordinator.js, speech-text.js | Entire source; RPC codecs/envelope/lifecycle, leases/dedup/backpressure, bounded audio/cache, browser playback | 126 tests pass against actual profile peers; no live browser/audio acceptance |
| tools/quantize_int8.py, bench_profile.py, paired_preprocessing_bench.py, verify_phase3.py | Entire source; offline side effects and evaluator validity | AST passed; no quantization, benchmark or HTTP test calls |
| tools/benchmark_phase2_profiles.mjs, verify_phase1_corpus.mjs, orchestrate_profiles.sh | Entire source; side effects, corpus/timing/error semantics | Syntax only; never execute systemd/credential-read orchestrator in this audit |
| evaluators/tts-preprocessing-20260927/evaluate.mjs | Entire source/policy/reference; immutable digest evaluator/negative controls | Full-v1 quality-only check passes; no timing mode |
| deploy/linux/{acceptance,activate,build-release,install-host,install-model,install-release,preflight,rollback,verify-health}.sh, lib/common.sh | Entire source; immutability, SHA checks, units/rollback boundaries and secret-safe health | Shell syntax passed; selection-only rollback reproducer on temporary synthetic directories |
| deploy/linux/systemd/{teratts.service,tailscale-control-443.service,tailscaled-control-443.conf}, ort-artifact.env | Entire text, documented operator scope and pinned artifacts | No current service state or firewall read/alteration |

## Main test/config/data/document coverage

- All 12 dsh-plugin/test/*.test.js files and helpers/runtime.js: read, executed 126 tests. Includes real Cordis/Registry/Client Gateway contracts, fake browser playback/autoplay/seek/URL cleanup, dedup/leases/cancel/unknown outcomes, endpoints/credentials/body caps and preparation/cache parity. Fixture technical-markdown.md used by frozen evaluator.
- All Rust embedded test modules read. Previous unchanged-code evidence: 146 passed, 4 ignored; historical Linux worker result, not executed by this audit.
- Cargo.toml and Cargo.lock: read/parsed; exact registry check covers 246 crates; 17 direct/development registry version queries. .cargo/config.toml, .gitignore, dsh-plugin/package.json and cordis.patch.yml read.
- Manifest model JSON inspected as pinned data; source validator inspected. src/lexicon.toml metadata/samples read and all entries parsed/validated structurally by a task-owned check (not every pronunciation listened to). RUAccent fixture read, pinned provenance and neural cases noted.
- README, NOTICE, relevant task specs, deployment/HTTP/speech integration docs, historical audit and latency evidence read. Historical specs with open checkbox states are not runtime truth; identified superseding records instead of changing archival history.
- LICENSE is third-party license text; .dsh reviews, cpuprofiles, state and evidence JSON are historical artifacts, not executable production code. Evaluator/quality hash and historical sample statistics validated. No claim of validating every past log statement.
- Existing untracked audio/package/images/private task artifacts are outside owned task scope and were not staged or uploaded.

## Unmerged branch coverage

### perf-autoresearch/teratts-opt (0d414b85d0e17fb340b5d7e6947177cb081c3881)

All net changed code reviewed: src/{tera,ruaccent,server}.rs, dsh-plugin/lib/client.js and added tests, service resource changes, .gitignore, benches/{benchmark_runner,quality_checks}.py, fixtures/holdout_cases.json and evaluator manifest. Buffer reuse commit followed by revert has no net source optimization. Browser malformed-tag cleanup is already superseded by current main; omograph variable rename is behaviorally the same lookup. Main already has opt-in actual inference warmup and startup normalizer construction. Additional eager style preload needs measured startup/memory/first-use evidence, not wholesale historical merge. Legacy local campaign state read as historical, not current configuration. No neural benchmark execution.

### agent/speech-front-integration (12c305abb03a52f51cc605f233a38fb8bafcb24d)

Unique commit and full new lexicon module reviewed; main lineage identifies squash equivalent 31581d9 (`... (#1)`) plus later correctness fixes. Reviewed parent-relative changes and compared current main behavior: branch code is superseded, not missing functionality. Full-current-tree reverse diff would remove unrelated later fixes, so do not merge old branch.

### task/private-voice-deep-hooks (be99bc74a13637b15cffbfb4ccc929b587cd71a7)

Runtime Rust/JS deltas fully reviewed, src/telemetry.rs and lib/private-telemetry.js read with their tests. Actual Rust tests not executed. All new executable tool sources were read:

- tools/nemotron-full/{nemotron_corpus_snapshot,run_nemotron_corpus,summarize_nemotron_corpus,voice_corpus}.py and tests/test_nemotron_corpus.py.
- tools/nemotron-pilot/{run_nemotron_pilot,summarize_nemotron_pilot}.py and tests/test_nemotron_pilot.py.
- tools/stt-dictionary/stt_dictionary.py, deploy/gateway-server.py, deploy/stt-dictionary.json and tests/test_stt_dictionary.py.
- tools/ultra-upgrade/ultra_asr.py, test_ultra_runtime.py, deploy/gateway-server.py and tests/test_ultra_adapter.py.
- tools/voice-teacher-pilot/{select_voice_teacher_pilot,run_voice_teacher_pilot,compare_voice_teacher_hints}.py and all three test files.
- tools/vocabulary-bank/{voice_corpus,vocabulary_bank,vocabulary_review,name_evidence,technical_terms,review_groups,blind_comparison,blind_challenge_set,model_comparison_review,repair_opening_intent,import_model_comparison,install_blind_challenge,vocabulary_capacity_smoke}.py; review-ui/{app.js,index.html,style.css}; deploy units; all nine test files.

All 47 Python source/test files parsed. Unit tests: vocabulary 48, dictionary 14, Nemotron full 7, Nemotron pilot 3, teacher 14, Ultra adapter 2 — 88 passed. Node suite with profile peers 135 passed. Temporary archive symlink used only for Node peers; no dependency installation. Model runtime smoke, million-row capacity smoke, pilot/full corpus runners, import/repair tools and real gateway were NOT executed. Docs/README/specs inspected; they explicitly describe source-only external backup, private data boundaries and prepared vs activated telemetry.

## Limits of “all code”

All owned executable code in main and unique unmerged tip changes was inspected. This does not mean all historical commits, generated/vendor/library code, model internals, current installed remote deployment, exhaustive pronunciation quality or every possible concurrency interleaving was verified. No independent worker review was available via an explicit approved pinned route. Broad web search was unavailable (HTTP 402); targeted primary APIs/docs succeeded, but technology discovery is representative rather than exhaustive. These limits are acceptance boundaries, not hidden unfinished implementation.
