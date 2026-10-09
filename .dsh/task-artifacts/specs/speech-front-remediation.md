# speech-front full remediation plan

Review: `speech-front-review-20260927-1916` (57 candidates → 43 confirmed, 7 duplicate, 7 rejected).
Judge verdict: sufficient / remediate.

## Completed Phases (Pushed to `agent/speech-front-remediation` in both repos)

| Phase / Finding | Fix | Commit |
|---|---|---|
| **Phase 1**: G1-01, G1-02, G1-03, G1-04, G1-06, G1-11 | Backported to `speech-front/src/normalize.rs` (+6 regression tests) | `01d244b` (`speech-front`) |
| **Phase 3 (Concurrency)**: O3-01, O3-02, O1-01 | `busy_timeout(5s)`, skip `IMMEDIATE` for v3 DB, `spawn_blocking` in `decision` | `01d244b` (`speech-front`) |
| **Phase 2**: G2-02, G1-05, G1-11 (server) | Extended Latin allowlist, leading-dot guard, year suffix deduplication | `7f99b6c` (`teratts-server`) |
| **Phase B (MEDIUM)**: B1 (`G1-07`), B5 (`G3-10`) | Zero-alloc `longest_match`, startup timestamp nonce in preview WAV cache | `2e1bba0` (`speech-front`) |
| **Phase B (MEDIUM)**: B2 (`G1-08`), B3 (`G2-01`), B4 (`G2-05`) | Narrowed `LexiconReload` mutex, silent unknown-tag stripping, pure-Cyrillic subprocess skip | `566844e` (`teratts-server`) |
| **Phase C (LOW correctness)**: G1-12, G2-04, G2-08, G3-01, G3-03, O1-04, O1-05 | Range unit suffixes, CLI `language_tags_removed` warning, script-transition split, ponytail updates, stdin/file size caps | `fbd86dd` (`speech-front`) |
| **Phase C (LOW correctness)**: G1-10, G1-12, G2-03, G2-07, G3-01, G3-04, O1-03, O1-07 | Cache `last_failed_revision`, range units, stdout newline trim, stderr limit → HTTP 400, `recv_timeout`, tag truncation | `84cd6bc` (`teratts-server`) |
| **Phase D (Modularity & Cleanup)**: G3-05, G3-06, G3-08, G3-11, G3-12, G3-13, G3-14, G3-15 | Extracted `src/detect.rs`, `src/lexicon_lock.rs`, `src/git_publisher.rs`; in-process `Renderer::TeraClient`; removed dead `Store::approve`; zero-alloc `has_candidate`; tightened CLI flags; batched SQLite child queries; inlined `escape_attr` | `fc327af` (`speech-front`) |

---

## Verification Evidence (Observed on `linux-worker`)

- **`speech-front`**: `cargo test --locked` → **76 passed** (19 lib + 57 bin), 0 failed; `cargo clippy --all-targets -- -D warnings` → **0 warnings** (exit 0).
- **`teratts-server`**: `cargo test --locked` → **142 passed**, 0 failed, 4 ignored; plus both cross-project integration tests (`cross_project_approve_reloads` and `installed_converter_cross_project`) **passed** against the built `speech-front` binary and `cmudict.db`.
- **Live CLI Reproductions (all 8 verified fixed)**:
  - `[G1-01]`: `Население две целых пять десятых миллиона и вес одна целая пять десятых килограмма`
  - `[G1-02]`: `Релиз двенадцатого августа две тысячи двадцать шестого года и 2026-08-12T14:30:00`
  - `[G1-03]`: `Система 64-bit, 12-factor и 7-zip`
  - `[G1-04]`: `Пакет node-v22.23.2`
  - `[G1-06]`: `Запрос на https://example.com/v1/chat/completions`
  - `[G1-11]`: `Дата двенадцатого августа две тысячи двадцать шестого года и двенадцатого августа две тысячи двадцать шестого года`
  - `[G1-12]`: `Дистанция десять — двадцать километров`
  - `[G2-04]`: `warnings: ["automatic_not_approved", "language_tags_removed"]`

---

## Remaining Deferred Architectural Task: Phase A — Drift Guard (G3-07)

**Selected Option:** **(a) Shared crate** (`speech-front` exports `normalize`, `teratts-server` depends on it, `teratts-server/src/speechfront.rs` is deleted).
**Prerequisite before execution:** Reconcile the repository boundary (`speech-front` private repo vs `teratts-server` GPL-3.0) and decide how `teratts-server` pulls the crate in CI/release builds (workspace path dependency vs Git/vendored crate). Both copies are now 100% behaviorally aligned after Phases 1, B, and C.
