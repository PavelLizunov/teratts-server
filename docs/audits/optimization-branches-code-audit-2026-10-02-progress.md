# Whole-code audit progress (not a final report)

## Snapshot

Main: `d937a90778824d1cb564a187f351ff400877cae8`. Audit branch: `task/optimization-branches-code-audit-20261002`. Inspection is read-only for source and deployment. No fixes, merges, deployments or benchmark campaigns are authorized by this audit.

## Branch map (initial fetched snapshot)

Counts are `main-only / branch-only`, not a claim of distinct code patches.

| Ref | Tip | Counts | Status |
|---|---|---|---|
| local agent/speech-front-remediation | 84cd6bc | 10 / 0 | Fully in main; old origin branch deleted |
| local feat/phase3-markdown-preparation | 715a117 | 23 / 0 | Fully in main despite ahead of old upstream |
| fix/server-markdown-default (local/origin) | e49dfd7 | 1 / 0 | Merged PR #5 |
| fix/tts-dsh-020-compatibility (local/origin) | cfa3259 | 6 / 0 | In main |
| local main | 5c015f4 | 10 / 0 | Behind GitHub main; untouched |
| perf-autoresearch/teratts-opt (local/origin) | 0d414b8 | 54 / 8 | Experimental branch requires net-change review |
| perf/phase2-cpu-tuning (local/origin) | 792941f | 29 / 0 | Fully in main |
| origin/agent/speech-front-integration | 12c305a | 19 / 1 | Unique history, but main has its own current lexicon reload implementation; compare contracts rather than blindly merge |
| origin/agent/speech-latency-gpu | eea5255 | 1 / 0 | Fully in main |
| origin/feat/phase3-markdown-preparation | a3bdbf2 | 29 / 0 | Fully in main |
| origin/task/private-voice-deep-hooks | be99bc7 | 4 / 21 | Separate substantial feature history: 73 files, approx. 5,523 added lines, not simply optimization |

Private-voice branch moved during earlier fetches. Review must pin `be99bc74a13637b15cffbfb4ccc929b587cd71a7` and record changes at final refresh. Includes STT plugins, Steam Deck launcher/runtime, audio health, teacher tooling and local converter code. All these branch-owned sources need an explicit coverage slice; they are not covered by inspecting only main's 19 Rust modules.

Autoresearch net patch includes eager style tensor loading, speechfront initialization, changed CPU/memory service quotas, standalone benchmark/quality evaluator, and browser helper changes. The buffer reuse commit is reverted within the branch. The `ruaccent` change merely names the same single `to_lowercase()` expression before lookup, so no speedup is established by the patch itself. Eager style loading is not an ONNX session warmup.

## Read coverage so far

- Main production: server lines 1–1189; primary lines 1–354; tera lines 1–889; main lines 1–250; full downloader, manifest, execution_provider, chunk, indexer, npy, rng, wav.
- Speech: ruaccent 1–939; russian_only 1–524; speechfront 1–300; textnorm 1–280; full markdown_speech.
- Plugin: index 1–569 and historical lifecycle inspection; full coordinator and speech-text; browser full-diff integration review but whole-module coverage remains pending.
- Documentation: README 1–260, performance and single-user task specs, preprocessing performance report, current deployment service and ORT artifact pin.
- Tools: quantize_int8 inspected. Deployment functions, remaining tools/evaluators, full tests and private-voice sources still pending.
- This is an inspection ledger, not proof all code has been audited or all apparent problems are real.

## Candidate issues to validate before reporting

1. Rust `chunk::hard_split` does not split a single word longer than 120 chars, and sentence splitting is not language-tag aware. Check CLI/server call contracts and existing tag tests before assessing correctness or actual cost.
2. `/tts` computes synthesis revision before refreshing lexicon (server 618 vs. 643); remote audio is labeled using gateway-local revision (server 818–824). Check cache freshness/primary ownership and reproduce without neural inference.
3. `LexiconReload::revision` hashes last approved raw lexicon, while startup/failed refresh can use builtin; evaluate whether revisions change with effective normalizer and whether plugin health refresh can detect edits without uncached synthesis.
4. `speechChunkLimits` validates first/next but not second size; determine reachable config surface, then classify as minor validation debt if only trusted internal use.
5. `prepareConfigured` calls unbounded `response.json()` unlike bounded audio/error readers; inspect endpoint trust and public Remote exposure before judging severity.
6. Prepared-text cache key includes current revision before discovery, while returned revision can change; check warmup/invalidation semantics and test a changing preparation backend before claiming a bug.
7. RUAccent classifier tensors copy inputs/outputs and omograph contexts clone token vectors; these are performance candidates only, not confirmed bottlenecks. Preserve pinned Python parity.
8. INT8 calibration tool builds random arrays without setting text_mask to ones and accepts arbitrary sorted tensor-name npz dictionaries. Inspect correctness, quality gates and user-facing docs. Do not quantize or benchmark during audit.

## Upstream research (fresh HTTP responses)

- [ONNX Runtime latest release API](https://api.github.com/repos/microsoft/onnxruntime/releases/latest) returned stable [1.30.0](https://github.com/microsoft/onnxruntime/releases/tag/v1.30.0), published 2026-09-10. Repo deployment artifact pin remains 1.27.0. Release notes include AVX2 LayerNorm/RMSNorm and NCHWc thread improvements plus reliability fixes. This warrants a compatibility/quality benchmark proposal, not an automatic update or promised speedup; GenAI KV cache features do not directly apply to this diffusion TTS pipeline.
- [ort release API](https://api.github.com/repos/pykeio/ort/releases/latest) returned [2.0.0-rc.13](https://github.com/pykeio/ort/releases/tag/v2.0.0-rc.13), same as repo pin, API 27. Verify runtime backward API compatibility before proposing a newer dynamic library.
- [TeraTTSv2 model API](https://huggingface.co/api/models/TeraSpace/TeraTTSv2) returned SHA `f05ea799094571a3553904a555df3834fb0b963b`, identical to repo pin. No newer revision is established for this model.
- General web search failed HTTP 402 (search endpoint balance). Configuration/credentials were not changed; primary URL fetches work and research continues through upstream APIs/docs. This is a coverage limitation for broad discovery, not a task blocker.

## Verification state

Previous integration task on identical main production source passed 126 Node tests, syntax/diff checks and reused recorded 146-pass/4-ignored Rust evidence. This audit has not yet executed additional checks. Cargo/rustc/shellcheck absent on current PATH; Python and Node are present. No independent worker review was dispatched because no explicitly pinned Gemini/Opus route is available and workflow orchestration was not requested.

## Round 1 verification and revised findings

- Fresh main Node suite: 126/126 passed. All deployment shell syntax checks and tools Python AST checks passed; no deployment scripts were executed. Frozen preprocessing evaluator checksums all passed.
- A first diagnostic attempt failed due to incorrect harness assumptions (`metaCache`, nonexistent `__dispatchRemote__`). Those failures are audit harness errors, not product findings. Corrected diagnostics passed 4/4 and are committed separately as reproducible audit evidence.
- Dismissed metadata failure re-dating suspicion: coordinator returns null without updating the successful metadata timestamp, so it retries on the next call.
- Dismissed heartbeat envelope suspicion: browser `apply` wraps all lease calls with `unwrapRemoteResult`, so the heartbeat sees the actual lease failure. Do not report the outer-envelope condition in isolation.
- Confirmed minor performance defect: first `prepareText` result is keyed before preparation revision discovery. First two identical calls make two HTTP preparations; third uses cache. Reproduced against isolated actual Cordis service. Applies to optional `prepareMode=on`.
- Confirmed minor validation debt: `secondChars` accepts a negative value while first/next validate. Public runtime uses defaults; custom helper use only, not a production severity claim.
- Rust installed toolchain located; `cargo test --offline --locked -j 1` was rejected by the host invariant guard before compilation. No override, worker job or new Rust execution. This is not a test failure in project code.
- HTTP pipeline uses `TeraEngine::chunk_preprocessed` / `chunk_tagged_text`, not raw `chunk::chunk_text`. Earlier narration incorrectly generalized that to CLI: CLI calls raw `chunk_text` before preprocessing each part and does not have the HTTP language-aware admission path. A >120-char well-formed tagged span is split into unmatched opener/closer portions; source-derived exact-path diagnostic confirms conditions, without Rust/model execution. A short sentence is packed together and is not a valid reproducer.

### Pinned private branch checks

Extracted exact Git archive `be99bc74a13637b15cffbfb4ccc929b587cd71a7` to a temporary read-only review tree; did not switch source branch or copy private deployment state.

- Dictionary suite: 14 passed; Nemotron corpus unit suite: 7 passed; teacher unit suites: 14 passed. These use temporary/mocked/local resources, no model inference or provider requests.
- Initial vocabulary test command failed to import `stt_dictionary`; the earlier narration incorrectly named disputes/review_disputes. Exact Git blob check and reread show those modules are not actual dependencies. Owning README explicitly sets `PYTHONPATH=tools/stt-dictionary`; with that documented environment all 48 tests pass. Candidate dismissed; no missing-source claim remains.
- Node suite: 133 pass, 1 file-load failure. `observed-synthesis.test.js` imports Host directly and cannot resolve profile-owned schemastery in clean archive; other tests correctly isolate/link actual profile dependencies. Fix test harness packaging, not claim runtime incompatibility. Do not install dependencies during audit.
- All 47 Python sources/tests in branch parsed via AST. Actual inference/remote runtime adapters not executed.
- Confirmed UI bug via isolated VM: `/github` and `/linux` initialize `state.tab` to `blind`, due to ternary/operator precedence in review-ui/app.js line 4. Browser interactions remain untested.
- Read feature telemetry sender/core branch diff, gateway Python, corpus storage, vocabulary collector/review and UI, STT dictionary, Ultra adapter, teacher runner, Nemotron runners/snapshot. Remaining review slices: voice pilot selectors/comparison utilities, shell/service scripts, vocabulary helpers, snapshot documentation and test bodies.
- Gateway snapshots use async `await file.read()` then enforce length, sync inference in async handlers and hardcoded deployment paths. Verify inherited/intended trust boundary and documented proxy limits before classifying; copying a complete deployed gateway into this repo is itself a maintenance concern, not proof that current production is vulnerable.

### Updated upstream research

- Registry snapshot for all 17 direct/development crates saved with primary-source URLs and observation timestamp (clock is now 2026-10-03 UTC). New patch updates: flate2 1.1.9 → 1.1.10, tokenizers 0.23.1 → 0.23.2. Breaking-line options: reqwest 0.12.28 → 0.13.5, sha2 0.10.9 → 0.11.0, toml 0.9.12 → 1.1.6. Not evidence of a vulnerability or reason for blanket upgrades.
- ORT threading documentation confirms bounded spin controls and per-session pools/NUMA tuning; GPU I/O binding can avoid host/device copies. Repo currently copies encoder/sampler outputs into host Vec then rebuilds tensors, so binding is a plausible GPU-only experiment, not a measured current CPU win.
- Model card documents alternate sampler1–sampler32 quality/speed tradeoff and streaming generator. Current server is pinned to sampler8 and buffers full WAV; streaming is a separate protocol change and sampler reduction requires perceptual quality checks.
- ort latest documentation says wrapper targets ORT 1.28; repo intentionally uses API 27 with dynamic runtime 1.27. Keep ABI/API pin explicit in upgrade plan rather than inferring newest wrapper means newest deployed runtime.

## Round 2 results

- All main production Rust modules and plugin modules were read, including embedded tests; main Node test bodies and deployment/tool sources inspected. Vendor lexicon is data, not a decomposition target. Branch-owned production sources read: telemetry, gateway copies, corpus/vocabulary/review helpers/UI, dictionary, teacher and Nemotron tools, Ultra adapter and units. Remaining test bodies/docs are bounded coverage verification, not authorization for model execution.
- Private Node suite with explicit symlink to actual profile peers passed 135/135; vocabulary documented environment passed 48/48; Ultra mocked adapter passed 2/2; dictionary 14/14, Nemotron 7/7 and teacher 14/14 already passed. No real model or external provider request executed.
- Source-derived CLI language-tag split and synthetic exact rollback selection conditions confirmed. Health/lexicon cache chain and primary revision propagation gaps recorded with source locations and a Host-only mocked diagnostic. Do not mislabel these as executed Rust integration tests.
- Frozen preprocessing quality evaluator executed in check-only full-v1 mode: quality true, empty/corrupted negative controls true; all immutable manifest checksums passed. No timing/benchmark run.
- Historical paired statistics recalculated: search median 169.379→0.624 ms (6 pairs); confirmation 321.267→1.026 ms (6 pairs); quality artifact hashes match. Valid narrow preprocessing result, not a neural TTS speedup. Legacy autoresearch quality script does not establish perceptual equivalence and resource changes confound efficiency claims.
- Fresh OSV queries for all 246 registry Cargo.lock packages returned rustls 0.23.43 / RUSTSEC-2026-0285 (TLS 1.3 message encryption-boundary bug, patched >=0.23.45, CVSS 5.3) and paste 1.0.15 / RUSTSEC-2024-0436 (informational unmaintained). Primary RustSec pages verified. No upgrade performed. Production runtime exposure not verified; loopback HTTP primary is not this TLS path, HTTPS downloader is.
- Primary technology sources: ORT 1.30, Rust 1.99, Qwen3-TTS (RU supported, 0.6B/1.7B, GPU-oriented quality/streaming candidate), Piper 1.8 (CPU alternative, RU voices, per-voice licenses), Kokoro model (no official Russian support established), TeraTTSv2 alternate samplers/streaming. No recommendation that any alternative is a proven upgrade on this hardware.
- DSH public GitHub latest release and client-ui-react npm latest endpoints returned 404. Protocol npm latest tag returned older 0.1.0-rc.6 than installed 0.2.0-rc.1; do not downgrade because dist-tag is stale. Current real-peer integration tests are stronger local evidence. No public DSH update claim.
- Branch-specific source findings captured in optimization-20261002/pinned-branch-findings.md; still partial, with corrected/dismissed suspicions explicitly preserved.

## Next work

Finish exact file-by-file coverage ledger and public technology/source report, review security priority and scan branch snapshot changes at final fetch. Synthesize concise final prioritized audit/branch recommendations with no hidden unexamined owned code, record practical verification limits, and publish documents/evidence only. Goal remains active.
