# Stage 4 Architectural Verdict: Astra (LLM-as-a-Judge)

- **Run ID**: `run-20260922-1407`
- **Evidence Basis**: `executive-evidence/v1`
- **Evaluator**: `ninitux/gpt-6-astra`

---

## 1. Evidence Sufficiency Judgment

```json
{
  "status": "limited",
  "rationale": "The reported test results, bounded live pilot, and lead-verified findings support prioritization and a targeted-remediation-first verdict. They do not establish Phase 3 readiness: the pilot did not exercise queue overflow, sustained concurrency, crash recovery, or revision-transition races. The packet also does not map the reviewed snapshot and findings to production release fd93361. Production exposure and broader reliability therefore remain partially unproven."
}
```

---

## 2. Architectural Risk Assessment

### Current Production Baseline (Profile D + `prepareMode: "off"`)
- **Assessment**: Observed operational stability with unresolved latent exposure. Not grounds for an emergency stop or roll-back of Profile D.
- Synthesis performance (Profile D on AMD 8845HS) is unaffected by preparation defects while `prepareMode: "off"`.
- However, `prepareMode: "off"` is not a universal shield for all findings:
  - `CACHE-01` (foreground generation gate staleness) lives on the normal synthesis path.
  - `SEC-01` (tag balancer output cap) affects the `/prepare` endpoint regardless of whether DSH is calling it.

### Future Phase 3 Activation (`prepareMode: "on"`)
- **Assessment**: Materially elevated coordination and resource-management risk if activated without prior remediation:
  1. `CONC-01` (Queue drop leaves ghost rejected Promise): could cause permanent key failure under load saturation.
  2. `CACHE-01` (Revision discovery rejects fresh audio): causes redundant network roundtrips after server updates.
  3. `LEASE-01` (Zombie leases from crashed tabs): can stall speculation beyond the 15-second lease window.
  4. `SEC-01` (Output cap breach by 5 bytes on 14.5k tags): breaks strict output limit invariants.

---

## 3. Evaluative Verdict

```json
{
  "verdict": "targeted_remediation_first",
  "architectural_justification": "Maintain the observed stable production baseline while resolving the verified output-bound and coordination/cache defects. Existing tests and the small shadow pilot support continued bounded operation, but do not justify broader Phase 3 activation. A blanket hold is disproportionate to the supplied operational evidence; unconditional proceed would disregard known correctness failures."
}
```

---

## 4. Concrete Remediation & Rollout Roadmap

1. **P0 (Critical Pre-Flight)**:
   - Fix `SEC-01`: Enforce 128 KiB limit across final tag balancing, preserving valid UTF-8 and the tag contract.
2. **P1 (Phase 3 Activation Gates)**:
   - Fix `CONC-01`: Wrap queue-admission wait inside `try/finally` so dropped waiters never leave ghost entries in `inFlightPrepares`.
   - Fix `CACHE-01`: Re-capture `this.cache.generation` after calling `invalidateRevision()` in `synthesize()`.
   - Fix `LEASE-01`: Lazily purge expired leases in `isForegroundActive()` by comparing `Date.now() > lease.until`.
3. **P2 (Quality of Life & Consistency)**:
   - Fix `CHUNK-01`: Align semicolon/newline punctuation rules between `client.js` and `speech-text.js`.
   - Fix `UI-01`: Mount the volume slider input element in the rendered player card.
   - Fix `PERF-01`: Assert cgroup presence in `bench_profile.py` and qualify README spinning claims.
