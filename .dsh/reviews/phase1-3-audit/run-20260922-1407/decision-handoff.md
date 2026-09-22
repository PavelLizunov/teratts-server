# Decision Handoff: TeraTTSv2 and DSH Plugin Comprehensive Audit

- **Run ID**: `run-20260922-1407`
- **Reviewed Snapshot**: `6432ad33..5e0490e` (19 commits, 23 files)
- **Arbitrator Verdict**: `targeted_remediation_first` (Astra LLM-as-a-Judge)

---

## Executive Summary

A comprehensive multi-model audit was executed across three independent specialist swarms (Gemini, Claude Opus, and xAI Grok) followed by lead source-of-truth verification and an architectural evaluation by GPT Astra.

The core conclusion is clear:
1. **Current Production is Sound and Stable**: The Phase 2 engine optimizations (Profile D: `First16Then32` + `spinning=0` on AMD Ryzen 7 8845HS) and DSH Plugin `0.8.7` operating in `prepareMode: "off"` demonstrate rock-solid stability and zero regressions.
2. **Phase 3 Activation Requires Targeted Fixes**: Before expanding server-side Markdown preparation into full production (`prepareMode: "on"`), 4 targeted defects (`SEC-01`, `CONC-01`, `CACHE-01`, `LEASE-01`) must be addressed and verified.
3. **Zero Production Disruption**: Throughout the audit, both `teratts.service` (CT 221) and `dsh-web.service` (`harness-test`) remained 100% uninterrupted.

---

## Actionable Next Steps

- [ ] **Step 1**: Implement P0/P1 fixes in a feature branch (`fix/audit-remediations`):
  - `src/markdown_speech.rs`: Bound `balance_language_tags` to `MAX_OUTPUT_BYTES`.
  - `dsh-plugin/lib/coordinator.js`: Fix queue-drop cleanup in `schedulePrepareJob` and add lease expiration check in `isForegroundActive`.
  - `dsh-plugin/lib/index.js`: Update `cacheGeneration` after inline revision invalidation in `synthesize()`.
  - `dsh-plugin/lib/client.js`: Align punctuation cuts and mount volume slider element.
- [ ] **Step 2**: Re-run automated verification (`cargo test --frozen`, `npm test` with targeted adversarial cases).
- [ ] **Step 3**: Re-execute bounded shadow pilot and verify clean metric collection.
- [ ] **Step 4**: Present remediation results for operator approval before enabling Phase 3 in production.
