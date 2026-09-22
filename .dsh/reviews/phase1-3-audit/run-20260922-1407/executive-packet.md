# Executive Evidence Packet: TeraTTSv2 and DSH Plugin Comprehensive Audit

- **Protocol Version**: `executive-evidence/v1`
- **Run ID**: `run-20260922-1407`
- **Snapshot Range**: `6432ad33a423703e6bf9059b69f8787315decfce..5e0490e27d5b1e0bc114c73e47f332fdc9c9b440` (19 commits, 23 files)
- **Review Date**: 2026-09-22
- **Lead Evaluator (SOL)**: Gemini Flash High
- **Participating Swarms**: Gemini Swarm (G1-G6), Claude Opus Swarm (O1-O4), xAI Grok Swarm (X1-X3)

---

## 1. System Context & Active Invariants

1. **Production Status**:
   - CT 221 is running release `fd93361` with Profile D (`First16Then32`, `spinning=0`) on AMD Ryzen 7 8845HS.
   - `dsh-web.service` on `harness-test` is running with `dsh-client-ui-teratts@0.8.7` with `prepareMode: "off"` (PID 3693502).
   - All services operated continuously without interruption or restarts during this audit.
2. **Current Work Tested**:
   - Phase 1: Step chunking (140 -> 240 -> 320), stage timing instrumentation.
   - Phase 1.5: Speculative pre-synthesis, round-robin cursor, `ByteBoundedAudioCache` (32 MiB / 4 MiB entry).
   - Phase 2: ORT `allow_spinning = "0"`, vocoder `First16Then32` (causal 20-frame context, bitwise WAV identity verified, SNR $\infty$ dB).
   - Phase 3A: CommonMark speech linearizer (`src/markdown_speech.rs`, `pulldown-cmark 0.13.4`, streaming 128 KiB limit, tables, task lists, code tag literalization).
   - Phase 3B: Server API `POST /prepare` and `input_format` in `POST /tts`, `MarkdownAdmission` (1 active, up to 8 queued), revision hashing.
   - Phase 3C: `PreparedTextCache` (16 MiB limit), `PrepareJob` deduplication, Shadow Mode non-blocking background comparison.
   - Runtime Fix: DSH 0.1.5-rc.2 settings API compatibility (`ctx.inject(["settings"])`), eliminating missing named exports.

---

## 2. Test Execution & Verification Evidence

- **Rust Server (`cargo test --frozen`)**: 139 passed, 0 failed, 4 ignored. Covers schemas, input validation, vocoder ranges, chunking, and markdown linearizer.
- **Node.js Plugin (`npm test`)**: 84 passed, 0 failed, 0 skipped. Covers chunking, client player helpers, coordinator leases, LRU caches, deduplication, isolated runtime imports against DSH 0.1.5-rc.2 `@deepseek-ai/*` packages, and Cordis lifecycle.
- **Controlled Shadow Pilot**: 10 prepare calls executed over Tailnet; 9 HTTP requests (1 deduplicated); 0 errors; 0 timeouts; 0 queue drops; server compute latency $< 1$ ms; 0 additional `/tts` calls generated; clean return to `prepareMode: "off"`.

---

## 3. Lead-Verified Defect Findings (SOL Filtered)

### P1 (High): SEC-01 — Output Limit Bypass via Language Tag Balancer
- **Path**: `src/markdown_speech.rs:241-244, 436-445`
- **Fact**: `OutputSink` halts parsing if emitted bytes exceed 128 KiB. However, `balance_language_tags` runs *after* `OutputSink` on the raw string and appends closing tags (`</ru>`, `</en>`) without checking the byte cap.
- **Impact**: 14,564 unclosed `<ru>` tags (58 KiB input) produce 131,077 bytes output, exceeding `MAX_OUTPUT_BYTES` (128 KiB).
- **Remedy**: Re-check output length after balancing before returning `Ok(PrepareOutcome)`.

### P2 (Medium): CONC-01 — Queue-Dropped Prepare Job Leaves Ghost In-Flight Entry
- **Path**: `dsh-plugin/lib/coordinator.js:400-444`
- **Fact**: When `prepareQueue` exceeds 8 items, the oldest waiter is rejected via `dropped.reject`. The rejected `await` inside the IIFE throws *before* entering the `try/finally` block. Therefore, `inFlightPrepares.delete(key)` is skipped for dropped jobs.
- **Impact**: Subsequent requests for the same key receive the stale rejected Promise from the deduplication map until process restart or revision change.
- **Remedy**: Move the queue-wait `await` inside the `try` block or add a `.catch()` cleanup handler.

### P2 (Medium): CACHE-01 — Self-Inflicted Cache Generation Staleness on Revision Discovery
- **Path**: `dsh-plugin/lib/index.js:370, 376, 380`
- **Fact**: In `synthesize()`, `currentGeneration = this.cache.generation` is captured before `await synthesizeConfigured()`. If the server response returns a new revision, `cache.invalidateRevision()` is called, incrementing `this.cache.generation`. Line 380 then calls `cache.set(key, audio, currentGeneration)` using the stale generation, causing the newly fetched audio to be rejected by the generation gate.
- **Impact**: Audio plays correctly, but is not cached on the first request encountering a new revision.
- **Remedy**: Re-capture `this.cache.generation` after calling `invalidateRevision()`.

### P3 (Low): LEASE-01 — Zombie Foreground Lease on Tab Crash
- **Path**: `dsh-plugin/lib/coordinator.js:302-304, 308-313`
- **Fact**: Leases are stored with `until: Date.now() + 15_000`, but `isForegroundActive()` only checks `activeLeases.size > 0` without evaluating timestamp expiry. If a tab closes abruptly, speculation stays paused.
- **Remedy**: Lazily purge expired leases in `isForegroundActive()`.

### P3 (Low): CHUNK-01 — Punctuation Break Divergence Between Client and Coordinator
- **Path**: `dsh-plugin/lib/client.js:216-224` vs `dsh-plugin/lib/speech-text.js:186-190`
- **Fact**: `speech-text.js` splits on semicolon (`; `) and newline (`\n`); `client.js` copy of `nextSpeechCut` omits them, causing different cut points and cache misses on text containing semicolons.
- **Remedy**: Align punctuation list in `client.js`.

### P3 (Low): UI-01 — Volume Slider Not Mounted in Rendered JSX
- **Path**: `dsh-plugin/lib/client.js:1150-1250`
- **Fact**: Volume state logic and methods exist, but the `<input type="range" class="teratts-volume">` element is omitted from the rendered player DOM tree.
- **Remedy**: Mount volume slider element in player DOM.

### P3 (Low): PERF-01 — Benchmark Throttling Assertion and Documentation Qualification
- **Path**: `tools/bench_profile.py:20-35`, `README.md:318`
- **Fact**: If cgroup stat file is missing, `read_cgroup_stats()` returns 0. README statement that `spinning=0` reduces CPU time "without degrading latency" is conditional on concurrent cgroup loads.
- **Remedy**: Assert cgroup file presence in benchmark; qualify README claim.

---

## 4. Architectural Questions for Astra (Evaluator)

1. **Evidence Sufficiency**: Is the evidence gathered across unit tests, live shadow pilot, and multi-swarm inspection sufficient to conclude that Phase 1, Phase 2, and the DSH 0.1.5-rc.2 compatibility fix are sound and stable in production?
2. **Systemic Risk Assessment**: Do the identified findings (SEC-01 tag balancer bypass, CONC-01 prepare ghost entry, CACHE-01 generation staleness) present immediate threats to system stability while `prepareMode` is `"off"`?
3. **Rollout Roadmap & Next Steps**: What is the recommended sequence of remediations and validation steps before proceeding to a full Phase 3 rollout (activating server-side Markdown preparation in production)?
