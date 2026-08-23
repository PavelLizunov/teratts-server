# TeraTTS/DSH full audit — 2026-08-23

Six read-only Gemini workers (`ninitux/gemini-3.7-flash-high`) audited non-overlapping areas. Lead review removed duplicates and downgraded unsupported claims. No runtime/config changes were made.

## Baseline

- Repository HEAD: `b28c80e731bb2f6c318f052b35b9fdd973820340`; working tree had one uncommitted diagnostic test in `src/speechfront.rs`.
- Active Rust release: `b11b631fb07acb67bc0d3a34544e9404e307d94c` (verified health); this backend is not code-drifted from HEAD — later commits are DSH client/docs only.
- Runtime: ORT_THREADS=2, PARALLEL_CHUNKS=2, SPEECH_FRONT=1, INT8 disabled; RSS ≈ 4.17 GiB in 5.5 GiB cgroup max.
- DSH: active plugin package 0.7.1; served client SHA equals installed client. `dsh --dump-config` warns `entry "time-context" not found`.

## Critical

None found.

## High — fix before further feature work

### H1. Timed-out/aborted requests keep CPU and admission permit
- Confidence: Proven
- Location: `src/server.rs:280-359`
- Evidence: `ActiveRequest` permit is moved into `spawn_blocking`; Tokio timeout/client drop cannot cancel blocking ORT/std threads. No cooperative cancellation checks exist between chunks.
- Impact: abandoned request keeps CPU, pool locks and the only active permit; queued requests may time out.
- Minimal fix: shared cancellation flag/token, set on timeout/drop; check before preprocess and every chunk; ensure all workers join and permit drops.
- Verify: abort a long request at 100ms; CPU and `queue.active` must return to zero before full synthesis duration.

### H2. Arbitrary endpoint can exfiltrate bearer token (SSRF)
- Confidence: Proven
- Location: `dsh-plugin/lib/index.js:10-17,33-59`
- Evidence: settings endpoint is unconstrained; resolved credential is attached to every configured destination.
- Impact: writable/malicious settings can POST the bearer to arbitrary internal/external URLs.
- Minimal fix: allow only loopback or explicitly trusted `*.tail9fd337.ts.net` HTTPS hosts before adding Authorization; reject other schemes/hosts.
- Verify: untrusted endpoint is rejected before DNS/fetch; trusted Tailnet URL succeeds.

### H3. Client text cleaning destroys language tags and snake_case
- Confidence: Proven
- Location: `dsh-plugin/lib/client.js:75-87`
- Evidence: `<[^>]+>` deletes `<ru>/<en>` tags; global `[*_~]` deletion turns `prepare_request` into `preparerequest`.
- Impact: manual language control is impossible and technical identifiers become unpronounceable.
- Minimal fix: preserve exact `<ru>/<en>` tags and replace `_` with a word boundary rather than delete it.
- Verify: cleanMarkdown preserves `<en>hello</en> <ru>мир</ru>` and outputs `prepare request` (or lexicon-approved spoken form).

### H4. Client seconds regex corrupts ordinary Russian
- Confidence: Proven
- Location: `dsh-plugin/lib/client.js:115`
- Evidence: `(number)\s*с` rewrites `5 с половиной`, `страница 10 с.`, and similar prepositional/abbreviation uses to `секунд`.
- Impact: incorrect text before TTS, including wrong grammar (`1 секунд`).
- Minimal fix: remove client heuristic; delegate units to speech-front, which has contextual unit rules.
- Verify: `5 с половиной`, `10 с.`, `8.0с аудио` normalize correctly under explicit test cases.

### H5. ISO `YYYY-MM-DD` is misread as range + negative number
- Confidence: Proven
- Location: `src/speechfront.rs:320-351,389-465`
- Evidence: date parser only accepts DD.MM.YYYY/DD/MM/YYYY; `2026-08-12` falls into numeric range and signed-number parsers.
- Impact: common ISO dates are spoken as nonsense.
- Minimal fix: parse valid ISO dates before ranges.
- Verify: `2026-08-12` → `двенадцатого августа две тысячи двадцать шестого года`.

### H6. One manual `+` disables chunking for an entire span
- Confidence: Proven
- Location: `src/tera.rs:156-162`, `src/textnorm.rs:66-84`
- Evidence: any span containing `+` is marked manual; `chunk_tagged` emits the entire span without applying MAX_CHUNK_CHARS.
- Impact: up to 2,000 chars can enter one ONNX request, causing latency/memory spikes or 180s duration rejection.
- Minimal fix: chunk at safe boundaries while preserving each marker and balanced tags.
- Verify: 1,500-char ru span with one `+` yields bounded chunks and identical marker count.

### H7. Profile depends on volatile `/tmp` taskboard tgz
- Confidence: Proven
- Location: `/var/lib/dsh/.dsh/profiles/web/package.json:6`
- Evidence: direct dependency is `file:/tmp/DSH-taskboard/shengsheng-dsh-taskboard-0.1.3.tgz`; previous `/tmp` cleanup caused `dsh plugin add` ENOENT. File currently exists but is volatile.
- Impact: plugin installs/upgrades become non-reproducible; after reboot/tmp cleanup package operations fail.
- Minimal fix: copy tgz into `/var/lib/dsh/.dsh/packages/` and update profile dependency/lockfile.
- Verify: remove temporary copy and run lockfile verification/install without ENOENT.

## Medium — next hardening pass

1. `src/server.rs:323-352`: creates one OS thread per chunk; early error detaches unjoined threads. Replace with bounded scoped workers and stop flag.
2. `dsh-plugin/lib/index.js:72-76` / client decode: full response exists simultaneously as ArrayBuffer, Buffer, base64, binary string, Uint8Array and Blob; enforce response-size ceiling before buffering.
3. `src/server.rs`, `src/tera.rs`: enforce `parallel_slots × intra_threads <= available cores`; startup currently trusts independent env values. Observed 2×4 slowdown confirms risk.
4. `dsh-plugin/lib/index.js:35`: `new URL("/tts", base)` strips configured reverse-proxy subpaths.
5. DSH client ignores Retry-After/retry_after_ms and maps queue congestion to a generic error.
6. Client table cells bypass `cleanLine`, leaving backticks/emphasis/link syntax raw.
7. Symbol replacements `→`/`×` inject Russian even for English voices; make language-aware or move to speech-front.
8. `src/speechfront.rs`: decimal-unit suffixes (`2.5 млн`, `1.5 кг`) remain abbreviated.
9. `src/speechfront.rs`: lexicon entries starting with punctuation may match inside URLs without a left boundary.
10. Engine pool RSS is ≈4.17 GiB at 2 slots; 4 slots likely exceed 6 GiB LXC/5.5 GiB service max. Enforce ceiling 2 for CT221.
11. DSH profile dependency includes `@deepseek-ai/dsh-time-context`, patch references it, but bundles omit it; dump-config emits a proven warning. Fix separately with a maintenance-window DSH restart.
12. Host plugin exposes internal endpoint/cause text in client-facing Toast; sanitize external error messages and log details host-side.

## Performance/evidence corrections

- Current documents mix different inputs: 3.65→2.3–2.5s (~1.5×) and 3.65→1.58s (~2.3×). Do not claim one global multiplier until a fixed corpus, warmup, 20 iterations, p50/p95 and identical RUAccent/speech-front flags are recorded.
- The 0.48s DSH RPC measurement used a different short input; it proves no obvious connection stall but is not comparable to long-paragraph compute.
- INT8 rejection proves the synthetic calibration was invalid for text_encoder, not that the architecture cannot be quantized. Real token IDs + real style embeddings and perceptual downstream metrics are required.
- TeaCache/TLC/DPM-Solver claims require model graph re-export/retraining for the monolithic pinned sampler; they are not drop-in runtime changes.
- Crossfade need is a Hypothesis, not Proven: independently synthesized chunk boundaries need waveform discontinuity measurement/listening before changing audio.

## False positives / rejected claims

- Parallel output ordering is deterministic: handles are created/joined in chunk-index order and seeds are index-based.
- Core model graphs/styles/indexer/rng/chunk logic match the known-good suflyor reference.
- Active backend b11b631 is not source-drifted from b28c80e; later changes are frontend/docs.
- Tailnet control-443 rule is narrow to control pool TCP/80 and does not block general HTTP.
- Current running client equals installed 0.7.1 by SHA.
- Speech-front itself preserves the tested technical sentence; user-observed omissions are more likely client cleanup/full-pipeline interactions.

## Recommended remediation order

1. H1 cancellation + bounded worker pool (combine with Medium #1/#3).
2. H2 endpoint/token trust boundary + response-size ceiling.
3. H3/H4/H5/H6 full text-normalization correctness pass with end-to-end corpus tests.
4. H7 persistent taskboard package; then time-context profile repair during an announced DSH restart.
5. Re-run fixed-corpus performance benchmark and update claims.
6. Only then resume new optimizations/features.
