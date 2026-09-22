# Scorecard: TeraTTSv2 and DSH Plugin Comprehensive Audit

- **Run ID**: `run-20260922-1407`
- **Snapshot Range**: `6432ad33..5e0490e2` (Phase 1 through Phase 3C + DSH 0.1.5-rc.2 fix)
- **Evaluation Date**: 2026-09-22
- **Lead Evaluator**: Gemini Flash High (SOL Verification)

---

## Multi-Vector Health Matrix

| Vector | Status | Evidence & Summary |
|---|---|---|
| **1. API Contracts & Schemas** | **PASS (Minor Gap)** | API schemas for `/tts` and `/prepare` strictly default to `Plain`. Header `x-teratts-synthesis-revision` correctly hashes model, lexicon, git SHA, and markdown revision. **Minor gap**: Output size limit (128 KiB) in `markdown_speech.rs` can be exceeded if thousands of unclosed `<ru>` tags are appended by `balance_language_tags`. |
| **2. Inference & Quality** | **PASS** | `First16Then32` windowing maintains exact 20-frame causal left context. Sample counts are exact ($L \times 3072$). Verification on real latents demonstrated 100% bitwise identity with `Fixed16` (Max error 0.000000, SNR $\infty$ dB). Stage timing logs are non-cumulative. |
| **3. Concurrency & Lifetimes** | **PASS (Minor Gaps)** | Tokio semaphore `Admission` and `MarkdownAdmission` correctly limit active requests. Cooperative cancellation stops threads at subchunk boundaries. Single-concurrency `prepareRunning <= 1` and `backgroundRunning <= 1` held. **Minor gaps**: Queue-dropped prepare jobs leak an entry in `inFlightPrepares`; foreground leases do not lazily reap expired `until` timestamps. |
| **4. Memory & Cache Bounds** | **PASS (Minor Gap)** | `ByteBoundedAudioCache` enforces 32 MiB budget and 4 MiB entry limit with LRU eviction. `PreparedTextCache` enforces 16 MiB and 128 entries. **Minor gap**: Captured `currentGeneration` becomes stale if foreground synthesis calls `invalidateRevision()` inline. |
| **5. Runtime Compatibility & Packaging** | **PASS** | `dsh-client-ui-teratts@0.8.7` completely eliminated invalid imports from `@deepseek-ai/dsh-settings`. Implements canonical `ctx.inject(["settings"])` pattern compatible with DSH `0.1.5-rc.2`. Defaults strictly to `prepareMode: "off"`. Tested against real runtime modules with 84 unit and lifecycle tests. |
| **6. Documentation & Rollback** | **PASS** | Two-level rollback runbook in `docs/deployment/linux.md` (Level 1: Fixed16 drop-in, Level 2: sha256 checksum check prior to `activate.sh`) is fully verified and matches physical files on CT 221. |

---

## Defect Summary

- **Critical (P0)**: 0
- **High (P1)**: 1 (Output cap bypass via language tag balancer in `markdown_speech.rs`)
- **Medium (P2)**: 2 (Queue-dropped prepare ghost entry, self-inflicted cache generation staleness)
- **Low (P3)**: 4 (Zombie lease on tab crash, semicolon/newline chunk divergence, missing volume slider UI, benchmark cgroup assertion)
