# Pinned unmerged-branch findings (partial evidence packet)

Pinned main `d937a90778824d1cb564a187f351ff400877cae8`, private branch `be99bc74a13637b15cffbfb4ccc929b587cd71a7`, autoresearch `0d414b85d0e17fb340b5d7e6947177cb081c3881`.

## Confirmed, scoped findings

### Medium, priority first: locked rustls matches a published TLS advisory

Main Cargo.lock:1436–1437 pins rustls 0.23.43. OSV exact-version queries covered all 246 registry lock entries and returned RUSTSEC-2026-0285; primary RustSec advisory states affected >=0.23.13,<0.23.45 and patched >=0.23.45, CVSS 5.3. This concerns acceptance of TLS 1.3 handshake messages across encryption boundaries; authenticated transcript remains intact, so do not claim arbitrary handshake takeover. Reqwest enables rustls-tls (Cargo.toml:16) and model downloader uses HTTPS. Inference primary is loopback HTTP, Axum inbound is plain HTTP, and external Tailscale HTTPS termination is outside this Rust TLS path. Confirm running binary dependency version separately before claiming active deployment exposure. Recommend a bounded transitive rustls patch upgrade with Cargo.lock review, worker tests and downloader TLS checks; no dependency change was performed.

Primary sources: https://rustsec.org/advisories/RUSTSEC-2026-0285.html and https://api.osv.dev/v1/vulns/RUSTSEC-2026-0285. The other returned advisory, paste 1.0.15 / RUSTSEC-2024-0436, is **unmaintained informational**, not an exploitable vulnerability; dependency comes through tokenizers. Track upstream replacement rather than emergency rewriting macros.

### Medium: CLI splits explicit language spans before validating them

Main `src/main.rs:309-320` calls raw `chunk::chunk_text` before `TeraEngine::synthesize`. Sentence packing can split a single well-formed `<en>...</en>` span across the 120-char boundary; each part is then passed to `ensure_language_tags`/validation, with unmatched opener or closer. HTTP instead preprocesses and then uses language-aware `chunk_preprocessed`; do not claim HTTP has this bug. Source-derived diagnostic demonstrates the broken two-part input; no Rust/model execution occurred. Minimal future fix: preprocess once and language-aware chunk, preserving stress markers and avoiding repeated RUAccent. Add long bilingual CLI tests before source change.

### Medium: automatic rollback does not mean previous activated release

Main `deploy/linux/rollback.sh:16-20` chooses the highest directory modification time excluding current, not a saved previous activation. Synthetic execution of the exact selection pipeline selects a newer installed-but-never-activated release instead of the prior release. No actual activation was performed. Use explicit SHA meanwhile; a future task can persist previous successful activation identity.

### Medium, cache correctness: lexicon-on-disk edits are invisible on repeated audio cache hits

`src/server.rs:408-421` health reads `current_synthesis_revision`; that in turn uses the last loaded `LexiconReload::revision`, not a filesystem refresh. Actual `lexicon.refresh` happens only when uncached request reaches text preparation (server 939; initial revision captured at 570). Host `synthesizeForeground` queries health then returns a cached audio value (index.js 369-406). If all repeated words remain cache hits after approved lexicon changes, no `/tts` call triggers refresh, so a 30-second health TTL is not an actual 30-second lexicon staleness bound. Isolated Host diagnostic confirms reuse under unchanged health revision; Rust half is source-derived, not integration execution. Do not fix by synchronous filesystem work on async health. Future fix: explicit safe revision invalidation/reload publication plus header revision tied to the exact effective snapshot; tests must cover invalid/unchanged exports and in-flight generations.

### Medium, primary-mode cache identity: primary revision is not returned to callers

`src/remote_primary.rs:145-191` validates status/WAV but discards primary synthesis revision header. Gateway `src/server.rs:570-580` labels primary output using its own code/model/lexicon hash. Updating primary assets/config while gateway stays unchanged cannot invalidate cached audio. Local revision also lacks voice/runtime/provider/ORT settings. Confirmed source contract gap, no current production update simulated. Future fix: composite effective backend+model/config revision with bounded trusted header validation and fallback distinction.

### Low: first preparation cache entry uses old revision

Main Host `index.js:319-343` computes key while revision is unknown, then learns returned revision and stores under the old key. With optional prepare mode on, first two identical requests invoke preparation twice, third hits. Current isolated real-Cordis diagnostic confirms. Compute admission/storage identity using actual returned revision and guard in-flight configuration generation.

### Low: custom second chunk limit is not validated

Main `speech-text.js:138-146` validates first/next sizes, not `secondChars`; browser equivalent should be kept in sync. Defaults are positive and no public user setting exposes custom second size, so this is helper contract debt, not a production exploit. Diagnostic confirms a negative custom value is accepted.

### Low: private review deep links choose wrong tab

Pinned private branch `tools/vocabulary-bank/review-ui/app.js:4`: ternary precedence makes all known named-term routes initialize to `blind`. VM check returns blind for `/github` and `/linux`. `tab()` expects GitHub/Linux names. Parenthesize named-route mapping vs blind fallback, add route initialization tests. No browser runtime used.

## Evidence weaknesses and maintenance recommendations (not security bug claims)

- Autoresearch runner/quality helper have no actual worker resource isolation, use fixed port and capture server stderr without draining it (`benches/benchmark_runner.py:54-59`, `quality_checks.py:50-54`). Small current workloads may not fill the pipe, but verbose/extended runs can deadlock or timeout. They also report CLI-style named variants as HTTP route `name` while server ignores this unknown field, so holdout labels do not prove phonetic/stress correctness.
- Legacy state records warmup/preload and later speechfront changes, but no paired confirmation/peak memory manifest/artifact-referenced quality gate for the final combination. Do not call 3.24→2.98 seconds a confirmed causal production win. Named omograph `to_lowercase` is not a distinct optimization; buffer reuse is reverted. CPU quota/memory increase changes resource budget, not algorithmic efficiency.
- `tools/bench_profile.py:153-168` labels all GET_HEALTH stage fields as None; no stage-duration capture despite claims. POST latency begins before complete HTTP body but measures full WAV, not first audio. `tools/verify_phase1_corpus.mjs:24-89` ignores HTTP response status and computes WAV duration from byte count before robust header checks; errors may become NaN/negative timing data.
- INT8 quantizer fallback calibration fills all float inputs randomly, including text_mask; it is not a representative voiced text calibration corpus. Named npz inputs/voice validation and perceptual gates are needed. Default FP32 is retained, so optional experiment, not automatic deployment recommendation.
- `sample_latent` and main synthesis duplicate encoder/duration/sampler orchestration. Shared minimal internal helper may reduce divergence if maintained actively; avoid broad rewrite without parity tests. Host/browser speech helper duplication is required by shipping shape today and has parity tests; copying it blindly into a third custom path is not recommended.
- Pinned private branch contains two byte-identical 416-line gateway snapshots. They are source backups of an external deployment, not authoritative current gateway configuration. Extract a shared external adapter/owning deployment repo rather than merging independent production copies here.
- Optional draft telemetry sends input state over Remote on every draft revision even when private ingest is off; Host then drops it. Gate browser instrumentation from an explicit capability/consent signal and debounce/bound draft events before activating. Prepared, not active, per owning branch docs; no claim about current collection was made.
- Private review feedback handler has explicit tailnet peer, Host, Origin, CSRF and revision checks; database/corpus permissions and quota checks are present. Avoid asserting 'no auth' just because no bearer token exists: actual trust boundary is tailnet allowlist.

## Disproved/incorrect initial suspicions

- Missing disputes/review_disputes modules was an audit narration error. Actual pinned imports are `stt_dictionary`; owning README explicitly requires `PYTHONPATH=tools/stt-dictionary`. Correct command passed all 48 tests. Git blob hashes match extracted files.
- Private Node direct import test fails in a clean archive lacking package peers, but passes once real profile node_modules is explicitly symlinked in the disposable archive. Full suite 135 passed, zero failed. Do not flag runtime incompatibility.
- Metadata failed refresh does not re-date successful cache timestamp; browser lease calls are unwrapped by `apply`, so rejection is visible. Both candidates dismissed by corrected diagnostics.
- A short tagged sentence is packed back together by raw chunk helper; CLI finding needs a tagged span exceeding packing limit. Source-derived diagnostic was corrected to this exact condition.

## Limits

No independent worker review, actual Rust/model execution, service restart, full browser visual/audio acceptance or unauthorized benchmark campaign. These are bounded audit findings and evidence gaps, not a claim that all current deployment services were checked.
