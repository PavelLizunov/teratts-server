# Optimization, all-branch and whole-code audit

## Objective and authorization

User requested a persistent goal covering all branches, all project code, optimization evidence and new applicable technologies. Active goal: `goal-eb921ca1-51ca-4815-9464-3f9b5d59b5aa`.

Deliver an evidence-based branch map, whole-owned-code coverage ledger, confirmed findings with exact locations and remediation, optimization evidence assessment and current upstream technology/dependency research. This is an audit, not authorization to implement fixes or deploy.

## Baseline and safety

- Audit branch: `task/optimization-branches-code-audit-20261002` from GitHub main `d937a90778824d1cb564a187f351ff400877cae8`.
- Pre-existing untracked artifacts remain untouched and excluded. No source, dependency, model, credential or runtime changes; no merges, deletes, direct main pushes or service restarts.
- Read-only audit pass first. Only task-owned records, report and bounded evidence are written, explicitly staged, committed and pushed to the dedicated branch.
- No new remote or load/quantization benchmark campaign. Historical measurements are labeled as historical and not proof of the active deployment.
- No user-authorized workflow orchestration or explicit pinned worker route exists in the current tools; inspect domain slices directly. No unpinned subagent inheritance.

## Coverage plan

1. All local and origin branch tips: ancestry, unique patches, intended functionality, stale branches and merge risk. Deep-inspect unmerged changes, including private-voice branch rather than assuming performance branches are the only pending work.
2. Rust HTTP, queueing, cancellation and remote primary (`server`, `remote_primary`, `main`).
3. Inference, models and formats (`tera`, `execution_provider`, `downloader`, `manifest`, `npy`, `rng`, `wav`, `indexer`, `chunk`).
4. Speech preparation (`speechfront`, `ruaccent`, `russian_only`, `textnorm`, `markdown_speech`, `num2words`, `lexicon_reload`, lexicon ownership).
5. DSH Host/browser, scheduling, caching and speech helpers; test coverage and runtime contracts.
6. Tools, deployment scripts/unit files, benchmark evaluators and documentation parity. Do not flag generated/test/data length as a defect.
7. Existing performance evidence: workload, baseline, quality controls, attribution, repeatability and actual merge state.
8. Upstream releases and practical new options using primary sources. Research date and source availability are explicit; do not assume a future release from the local clock.

## Verification

- Safe Node regression/syntax checks and shell syntax checks; inspect tooling side effects before running anything.
- Cargo is not on the default PATH, but the installed toolchain was found later. Its wrapper explicitly forbids local compilation on this control-plane host; an offline one-job attempt was rejected before compilation. Do not override the guard or start an unauthorized remote build. Record Rust execution limits and reuse historical evidence only for unchanged code.
- No dependency installs, arbitrary package execution, model downloads or inference stress tests.
- Findings require source evidence and reachable conditions; distinguish confirmed bug, suspicion and optional improvement.
- Report actual covered/uncovered files and independently reviewed/not independently reviewed status.
- Final GitHub check: all task commits published and unrelated files unchanged.

## Initial scout

- 19 Rust source files; four production plugin JS modules; tools/evaluator/deployment sources included. Approx. 17,454 lines including tests embedded in Rust, lexicon data and deployment/config data, so this is not a production LOC defect score.
- Most branches are ancestors of main. Outstanding histories: autoresearch 8 commits (with a reverted buffer experiment), speech-front-integration 1 commit, private-voice-deep-hooks 21 commits at the initial snapshot. Remote private-voice branch changed during earlier fetches, so pin review to the captured hash and refresh at completion.
- Local main is 10 commits behind origin/main; leave it untouched during audit. Local phase3 is ahead of its old upstream but fully included in main.

## Progress

Audit started; no final findings or completion claimed.
