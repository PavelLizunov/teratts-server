# speech-front sequential-review/v2 — REPORT

**Run ID:** `speech-front-review-20260927-1916`
**Snapshot:** `speech-front@2cce5ebf` + `teratts-server@715a117e`
**Status:** complete | Profile: strict/exact | Independence: context_only
**Judge sufficiency:** sufficient | **Recommendation:** remediate

---

## TL;DR

57 кандидатов от 6 рецензентов (Gemini × 3, Opus × 3) → **43 подтверждены, 7 дубликатов, 7 отклонены**. Судья (Opus, изолированный контекст): **sufficient / remediate**. Ни одного CRITICAL, **5 HIGH**, 11 MEDIUM, 27 LOW. Все 5 механических проверок пройдены (99 юнит-тестов + clippy + 2 кросс-проектных интеграционных + 8 CLI-репродукций).

---

## Confirmed Findings by Severity

### HIGH (5 — blocking)

| ID | Location | Issue |
|---|---|---|
| **G1-01** | `sf/normalize.rs:460-464` | `!decimal` guard skips unit expansion for decimal numbers (`2.5 млн` → `две целых пять десятых млн`). Reproduced. |
| **G1-02** | `sf/normalize.rs:214-221` | Missing `parse_iso_date` corrupts `2026-08-12` into range `2026–8` + `-12`. Reproduced. |
| **G1-06** | `sf/normalize.rs:183-196` | `boundaries_match` allows `/v1/chat/completions` to match after `example.com`. Reproduced. |
| **G2-02** | `ts/russian_only.rs:302-317` | `normalize_symbols` strips `café` → `caf ` (non-ASCII Latin replaced with spaces). Source-proven. |
| **G3-07** | `ts/speechfront.rs:1-1166` | 1,166 LOC vendored fork of `normalize.rs` (1,003 LOC) — root cause of G1-01..G1-07 drift. Source-proven. |

### MEDIUM (11)

| ID | Location | Issue |
|---|---|---|
| G1-03 | `sf/normalize.rs:441-446` | `64-bit`, `7-zip` expanded into Russian numbers. Reproduced. |
| G1-04 | `sf/normalize.rs:255-266` | `node-v22.23.2` version parsed without `attached_to_identifier`. Reproduced. |
| G1-07 | `sf/normalize.rs:159-172` | `longest_match` allocates two `String`s per entry per position. |
| G1-08 | `ts/lexicon_reload.rs:53-66` | Mutex held across disk read + SHA-256 + TOML parse. |
| G1-11 | `ts/speechfront.rs:354-371` | `parse_numeric_date`/`parse_iso_date` don't consume `года`/`г.` → `года года`. Reproduced. |
| G2-01 | `ts/russian_only.rs:408-428` | `flatten_tags` speaks `<div>` as "div" vs speech-front rejects unknown tags. |
| G2-05 | `ts/server.rs:904-913` | Subprocess spawned for 100% Cyrillic text in `russian_only` mode. |
| G3-10 | `sf/review.rs:269-285` | Audio cache `{pid}-{seq}.wav` collides after PID reuse. |
| O1-01 | `sf/review.rs:131-196` | `std::sync::Mutex` blocks async executor across SQLite + git push. |
| O3-01 | `sf/observe.rs:129-133` | No `busy_timeout` → instant `SQLITE_BUSY` on concurrent access. |
| O3-02 | `sf/observe.rs:142-257` | `IMMEDIATE` write transaction on every `Store::open()`, even read-only. |

### LOW (27)

G1-05, G1-10, G1-12, G2-03, G2-04, G2-07, G2-08, G3-01, G3-03, G3-04, G3-05, G3-06, G3-08, G3-11, G3-12, G3-13, G3-14, G3-15, O1-02, O1-03, O1-04, O1-05, O1-06, O1-07, O3-03, O3-06, O3-07.

### Duplicates (7)

G2-06→G1-08, G3-02→G3-01, O2-01→G1-03, O2-02→G1-02, O2-03→G1-01, O2-04→G1-05, O3-04→O1-01.

### Rejected (7)

G1-09 (O_NONBLOCK intentional for x86_64 Debian), G3-09 (lock file rejection is tested invariant), O1-08 (192-bit CSRF adequate), O2-05 (transient double spaces cleaned), O2-06 (em-dash → hyphen documented), O2-07 (UTF-8 slicing provably safe), O3-05 (crash window explicitly documented).

---

## Mechanical Checks

| Check | Result |
|---|---|
| check-1: `cargo test` speech-front | 68 passed, 0 failed |
| check-2: `cargo clippy` speech-front | 0 warnings |
| check-3: `cargo test` teratts-server (speechfront + russian_only + lexicon_reload) | 31 passed, 0 failed |
| check-4: lexicon.toml diff | Byte-identical (186 entries); normalize.rs vs speechfront.rs: 646 diff lines |
| check-5: Cross-project integration + CLI reproductions | 2 integration tests passed; 8 defects reproduced verbatim |

---

## Key Architectural Themes

1. **Cross-Repo Normalization Drift** (G1-01, G1-02, G1-06, G3-07 + 4 MEDIUM): `teratts-server/src/speechfront.rs` is a vendored fork with 646 diff lines. Fixes go in one direction only — ISO dates, decimal units, hyphenated identifiers, URL boundary, zero-alloc matching added to server but never backported to `speech-front`. Server also dropped `.NET` dot guard (G1-05). Both have `года года` bug (G1-11).

2. **`russian-only` Contract Drift** (G2-02, G2-01, G2-05): Server's `normalize_symbols` strips extended Latin (`café` → `caf `). `flatten_tags` speaks `<div>` as "div". Subprocess spawned even for pure Cyrillic.

3. **Concurrency & Lock Contention** (G1-08, O1-01, O3-01, O3-02, G3-10): No SQLite `busy_timeout`, `IMMEDIATE` on every open, sync mutex in async handler, PID-recycled cache names.

---

## Ponytail Debt Ledger

| Location | Ceiling | Status |
|---|---|---|
| `sf/normalize.rs:93` | 162 entries | **BREACHED** (186) |
| `ts/speechfront.rs:94` | 162 entries | **BREACHED** (186) |
| `sf/pronounce/mod.rs:152` | beam of 3 | Valid (dedup enforces), **no-trigger** |
| `ts/russian_only.rs:153` | single process | Valid, **no-trigger** |
| `sf/scripts/pre-agent.ps1:9` | 2 hooks | Valid |
| `sf/scripts/post-agent.ps1:15` | 2 hooks | Valid |
| `ts/tera.rs:673` | 1 short shape | Valid |

---

## Judge Verdict (Opus, context-independent)

**Sufficiency:** sufficient — robust evidence across 4 dimensions (reviewer convergence, mechanical checks, evidence grading, coverage completeness).

**Recommendation:** remediate — 5 HIGH findings are blocking; 3 reproduced on live CLI.

**Acceptance Conditions:**
1. Backport G1-01, G1-02, G1-06 fixes to `speech-front/src/normalize.rs` with regression tests.
2. Fix G2-02: extend `normalize_symbols` Latin allowlist to `0x00C0..=0x024F`, `0x1E00..=0x1EFF`, `0xFB00..=0xFB06`, `0xFF21..=0xFF5A`.
3. Establish drift guard for G3-07: common crate or CI diff-gate.
4. Fix G1-11 `года` duplication in both copies.
5. Address MEDIUM concurrency cluster (O3-01 busy_timeout, O3-02 conditional migration, O1-01 spawn_blocking) before multi-user deployment.
6. Re-run checks 1–5 at remediated snapshot.

---

## Limitations

- No HTTP load/concurrency testing or fuzz testing performed.
- Context-only independence (same model family in both reviewer and judge pools).
- Token/billing usage unknown.
- Review server HTTP/CSRF/Git checks verified via unit tests and source inspection, not live penetration testing.
- Licensing constraint (proprietary vs GPL-3.0) noted but not legally evaluated.

---

## Bundle Contents

```
.dsh/reviews/speech-front-review-20260927-1916/
├── manifest.json          # validated sequential-review/v2 manifest
├── findings.json          # 57 candidates with full disposition
├── packet.json            # frozen evaluator input (23,970 chars)
├── REPORT.md              # this file
├── reports/
│   ├── attempt-g1.json    # lane-g1 raw report (12 candidates)
│   ├── attempt-g2.json    # lane-g2 raw report (8 candidates)
│   ├── attempt-g3.json    # lane-g3 raw report (15 candidates)
│   ├── attempt-o1.json    # lane-o1 raw report (8 candidates)
│   ├── attempt-o2.json    # lane-o2 raw report (7 candidates)
│   ├── attempt-o3.json    # lane-o3 raw report (7 candidates)
│   └── attempt-judge.txt  # judge verbatim response
└── evidence/
    ├── check-1-speech-front-test.txt
    ├── check-2-speech-front-clippy.txt
    ├── check-3-teratts-speechfront-test.txt
    ├── check-4-cross-repo-diff.txt
    ├── check-5-cross-project-and-repros.txt
    └── check-6-source-excerpts.txt
```
