# Integrate latest fixes into GitHub main

## Intended result and authorization

The user requested integration of the latest fixes into the main branch. Open and merge a GitHub pull request from the existing dedicated `fix/server-markdown-default` branch into `main`, retaining the existing commit history. Do not push directly to main.

## Snapshot and scope

- Initial base: `5c015f4e7660311154c6ba331b00ea6b4d4e1caa` (`origin/main`).
- Initial head: `3928980811141bef65f3a1aa97116c3c2e9b2d01`.
- Eight commits cover DSH 0.2.0 plugin compatibility and strict Remote codecs, server Markdown defaults, regression tests, owning README and recorded deployment/playback acceptance.
- Reuse the existing dedicated branch; add only this task record. No source implementation change is planned.
- Preserve all pre-existing untracked artifacts, other branches, credentials, services and runtime configuration. No deployments, restarts, direct main pushes, force pushes or remote branch deletion.

## Verification and integration procedure

1. Refresh GitHub refs, check that no open duplicate PR exists, and review the complete base-to-head diff.
2. Run the plugin Node suite against the actual profile dependencies, syntax checks and `git diff --check`.
3. Reuse recorded Rust evidence only if the source, Cargo manifest and lock are unchanged from tested `5cff27e744a19d24350ef32dc061f48bc2a23f00`: 146 passed, 4 ignored on the Linux worker. Cargo is unavailable on the current PATH; no new remote build is planned.
4. Commit and push only the task record; open the PR, inspect mergeability and checks, then merge with a head-SHA guard if GitHub policy permits and no failing checks exist. Keep the source branch.
5. Fetch main and confirm the exact integrated head is its ancestor and no committed task changes remain unpublished.

## Unknowns and limits

- GitHub merge protection/check requirements are checked on the PR before merging. No repository workflow files are present.
- Independent review is not available through the current explicit Gemini/Opus tool routes; review is coordinator-only.
- Prior live deployment and user-confirmed playback evidence is recorded in the existing task specs; it is historical evidence, not newly executed live acceptance.
- Untracked local-only artifacts are explicitly excluded by the user's follow-up scope.

## Results

- Refreshed origin; no duplicate open PR exists. Initial main is an ancestor of the source branch.
- Reviewed the complete 13-file integration diff, including source, package peers, README, regression fixtures and existing verification records. No new runtime implementation is added in this integration task.
- Current execution: `node --test dsh-plugin/test/*.test.js` passed 126/126, zero failures/skips; real profile Cordis, Typert Registry and Client Gateway integration tests passed. `node --check` for both client and Host and base-to-head `git diff --check` passed (all exit 0).
- Exact comparison against `5cff27e744a19d24350ef32dc061f48bc2a23f00` confirms no changes in `src/`, Cargo.toml or Cargo.lock. The 146-pass/4-ignored Rust result is reused historical evidence, not a new test run.
- Focused trust-boundary inspection: authorization still precedes bounded Markdown preparation; forward requests explicitly use plain format; browser credentials and endpoint access remain Host-owned; Remote mounting errors propagate before slot registration. No new differential blocker was confirmed. Not a full security certification or visual/live playback check.
- GitHub PR mergeability and check status will be verified after publication. Merge outcome is recorded in the PR and reported after fetching and verifying main; this pre-merge record does not claim the merge has already happened.
