# TeraTTS & DSH Integration: Large-Scale Swarm Audit Report (2026-09-02)

**Audit Team:** 6-worker Gemini Swarm (`ninitux/gemini-3.8-flash-high`) + Lead Model Integration  
**Scope:** Full-stack inspection of `dsh-plugin/lib/client.js`, `dsh-plugin/lib/index.js`, `dsh-plugin/cordis.patch.yml`, `src/server.rs`, `src/tera.rs`, `src/speechfront.rs`, `src/ruaccent.rs`, `src/textnorm.rs`, `src/num2words.rs`, `src/wav.rs`, `src/chunk.rs`, and `deploy/linux/*`.  
**Safety Constraint:** Zero DSH restarts or disruptions.

---

## 1. Executive Summary

A comprehensive, end-to-end audit was conducted to identify why TeraTTS periodically disconnects, hangs, or fails in DSH, and to establish concrete optimization paths for latency reduction, code simplification, and architectural resilience.

The investigation revealed that failures are caused by a chain of compounding issues across all three layers of the architecture (Browser Client, DSH Host Plugin, and Rust Inference Server):
1. **The Server Layer:** A shallow queue (`capacity: 2`), an admission permit release race condition on cancellation, CFS CPU throttling under systemd `CPUQuota=400%`, and an unconditional panic in `num2words.rs`.
2. **The DSH Host Layer:** Zero retries on transient network errors or HTTP 429/503 queue saturation, a standard-library `AbortSignal.timeout` bug masking timeouts as generic failures, and >140 MiB heap churn per 16 MiB WAV payload over Cordis RPC.
3. **The Browser Client Layer:** Browser Autoplay Policy blocking on subsequent chunk playback, catastrophic abort of active playback on a single chunk error, buffer starvation between Chunk 0 and Chunk 1, and audio glitches from sequential `HTMLAudioElement` instances.

---

## 2. Root Causes of Instability ("Почему отваливается")

### 2.1 Critical Admission Permit Release Race Condition (`src/server.rs`)
* **Mechanism:** In `server.rs`, `ActiveRequest` (holding the admission permit) is owned by the async Axum request future, while actual ONNX synthesis runs inside `tokio::task::spawn_blocking`.
* **The Failure:** When a client aborts or hits a timeout, the async handler future drops immediately, decrementing `admitted` and releasing the semaphore permit **while the blocking thread is still running ONNX inference on `pool[0]`**.
* **Impact:** A newly admitted request immediately enters `spawn_blocking` and stalls on `pool[0].blocking_lock()`. If multiple requests cycle, head-of-line blocking cascades, causing artificial latency spikes and premature timeouts.

### 2.2 Server Queue Starvation & Rejection (`MAX_ADMITTED_REQUESTS = 3`)
* **Mechanism:** Concurrency on CPU is strictly serialized (`active: Semaphore::new(1)`), and total admitted requests are capped at `MAX_ADMITTED_REQUESTS = 3` (1 active + 2 waiting).
* **The Failure:** When progressive chunking dispatches 4+ chunks rapidly, or when multiple browser tabs or repeat clicks occur, any 4th request is instantly rejected with **HTTP 429 Too Many Requests** (`{"code":"busy","message":"synthesis queue is full","retry_after_ms":1000}`).

### 2.3 Host Plugin Zero-Retry Behavior on 429/503 & Network Blips (`dsh-plugin/lib/index.js`)
* **Mechanism:** In `lib/index.js`, `fetch()` has no retry loop.
* **The Failure:** When the server returns 429 (`busy`) or 503 (`queue_timeout`), `index.js` extracts `retryAfterMs` into an error property and **immediately throws an error**. Likewise, any transient Tailscale / WireGuard re-keying blip (`ECONNRESET`, `ETIMEDOUT`, `UND_ERR_SOCKET`) immediately terminates the request.

### 2.4 Catastrophic Abort on Single Chunk Error (`dsh-plugin/lib/client.js`)
* **Mechanism:** In `client.js`, chunk synthesis runs inside a monolithic `try ... catch` loop.
* **The Failure:** If Chunk 3 out of 10 encounters a transient 429 or network blip, `catch (error)` invokes `failPlayback()`.
* **Impact:** `failPlayback()` immediately calls `releaseMedia()`, pausing active audio, revoking all Blob URLs, and wiping `playback.segments = []`. Even though Chunks 0, 1, and 2 were synthesized and currently playing, **the audio abruptly dies mid-sentence**.

### 2.5 Browser Autoplay Policy Blocking Subsequent Chunks (`dsh-plugin/lib/client.js`)
* **Mechanism:** Chunk 0 starts from a direct user click (`startPlayback`), satisfying browser user activation (`navigator.userActivation.isActive`).
* **The Failure:** When Chunk 0 finishes, `advancePlayback` triggers from `audio.onended` (asynchronous browser event loop with zero user gesture). Calling `await segment.audio.play()` on a brand new `new Audio(url)` instance is rejected by Safari (WebKit) and strict Chromium profiles with:
  `NotAllowedError: play() failed because the user didn't interact with the document first.`
* **Impact:** Playback stops immediately after the first sentence with an "Audio playback failed" error.

### 2.6 Buffer Starvation between Chunk 0 (240 chars) and Chunk 1 (800 chars)
* **Mechanism:** Chunk 0 is cut at sentence boundaries to $\le 240$ characters (often only 30–60 characters for short phrases like *"Вот список изменений:"*), which plays for only 1.5–2.5 seconds.
* **The Failure:** Chunk 1 is 800 characters and takes 3.0–5.0 seconds to synthesize. Chunk 0 ends before Chunk 1 finishes synthesis. Audio cuts out, UI switches to a spinning loader, and when Chunk 1 finally arrives, programmatic `.play()` without a gesture is blocked by the browser.

### 2.7 CFS CPU Quota Throttling (`CPUQuota=400%` in `deploy/linux/systemd/teratts.service`)
* **Mechanism:** CFS allows 400ms of CPU time per 100ms window (4 cores).
* **The Failure:** `install-host.sh` sets `TERATTS_ORT_THREADS=4` and `TERATTS_PARALLEL_CHUNKS=2` (8 compute threads). 8 active threads consume the 400ms quota in 50ms, causing the Linux kernel to **freeze all threads in the cgroup for the remaining 50ms of every 100ms period**. This causes severe p99 latency spikes, socket timeouts, and probe failures.

### 2.8 Memory Pressure & OOM Risk (`MemoryHigh=5G`, `MemoryMax=5500M`)
* **Mechanism:** Baseline RSS for 2 model slots + RUAccent is ~4.17 GiB.
* **The Failure:** Headroom to `MemoryHigh` is only 830 MiB, and buffer to `MemoryMax` is 380 MiB. Long syntheses with transient tensor allocations and WAV encoding breach 5G (triggering synchronous kernel page reclaim stalls) or breach 5500M without swap (triggering an immediate kernel `SIGKILL` OOM).

### 2.9 PMTU Black Hole on WireGuard & NAT Keepalive Expiry
* **Mechanism:** The WireGuard interface (`tailscale0`) has an MTU of 1280 bytes (vs LAN 1500). Large binary WAV payloads (500 KB – 5 MB) attempt full-sized TCP segments.
* **The Failure:** If intermediate routers drop ICMP "Fragmentation Needed" packets, large audio responses stall indefinitely while small `/health` requests succeed. Additionally, multi-second inference compute without intermediate byte streaming causes NAT mappings to expire, resulting in `ECONNRESET`.

### 2.10 Unconditional Worker Panic in `src/num2words.rs`
* **Mechanism:** Lines 87 & 131: For English integers $\ge 2\times 10^{12}$ (e.g. `num2words("2000000000000", "en")`), `spell_below_1000_en` attempts to index `EN_UNITS[20]`. Because `EN_UNITS` has length 20 (indices `0..19`), this triggers an **unconditional array out-of-bounds panic**, crashing the worker thread.

---

## 3. Latency Optimization & Improvement Paths

### 3.1 Inference Latency Breakdown (`src/tera.rs`)
Analysis of `TeraEngine::synthesize` reveals that **>97% of CPU compute time** is consumed by only two models:
* **Vocoder (`vocoder.onnx`):** **~58.6% of time (~1,700 ms)**. The causal overlap-save streaming loop evaluates 36 frames to output 16 new frames per step, imposing a **2.25× redundant computation tax** on the convolutional upsampler.
* **Sampler (`sampler_distilled_cfg3_8step.onnx`):** **~37.9% of time (~1,100 ms)**. Evaluates 8 distilled diffusion steps across 144 latent channels with cross-attention.
* **Text Encoder & Duration Predictor:** **<3.0% combined (~75 ms)**. Prior optimization attempts mistakenly focused on quantizing the encoder (the ~1% component).

### 3.2 Eliminating In-Memory Clones & Disk I/O Hotspots
1. **Preload Style Embeddings:** `TeraEngine::synthesize_preprocessed` opens, reads, and parses `style_ttl.npy` (51.2 KB) and `style_dp.npy` from disk on **every single synthesis request**. Preloading them into RAM eliminates redundant disk I/O.
2. **Eliminate 442 KB Deep Clone in Vocoder:** In `src/tera.rs`, each 16-frame vocoder step deep-clones 442 KB of audio samples in `named_output_f32`, plus an additional 196 KB slice. For a 24-chunk sentence, this generates **>15 MB of transient heap churn**. Slicing borrowed tensor views directly eliminates this overhead.
3. **Pre-warmed TOML Normalizer:** On the first Russian request, `speechfront::Normalizer::builtin()` parses an embedded 1,160-line TOML file synchronously. Normalization must be pre-warmed at server boot.

### 3.3 RUAccent Latency & Regex Optimization (`src/ruaccent.rs`, `src/speechfront.rs`)
1. **Dynamic Regex Recompilation:** In `src/ruaccent.rs:517`, `Regex::new(r"\s+([,.?!:;…])")` is compiled on the hot path for every homograph resolution. Moving it to `std::sync::LazyLock` eliminates redundant regex parsing.
2. **Avoid Tokenizer Clones:** In `ruaccent.rs`, `PairClassifier::choose` clones the Hugging Face `Tokenizer` struct on every homograph resolution to mutate truncation. Configuring truncation once at load time eliminates hundreds of allocations per sentence.
3. **Lexicon Matching Overhead:** In `speechfront.rs`, `Normalizer::longest_match` performs a linear scan over 162 lexicon entries at every character offset with `.to_lowercase()`, generating up to 32,400 heap allocations for a 100-character input. Pre-lowercasing lexicon entries or using an `AhoCorasick` automaton achieves an $O(N)$ scan.
4. **RUAccent Caching:** In `Full` mode, RUAccent executes 3 to 20+ ONNX inferences per sentence (adding 150–400ms latency). Introducing an LRU cache (e.g. 2048 entries) for out-of-dictionary accentuations dramatically reduces inference frequency.

### 3.4 Audio Architecture: Web Audio API (`AudioContext`)
Replacing sequential `new Audio(url)` elements with a single `AudioContext` and scheduled `AudioBufferSourceNode`s provides:
* **Zero Autoplay Rejections:** Unlocking `AudioContext.resume()` synchronously in the user click handler ensures all future audio chunks can be scheduled without user activation.
* **Sample-Accurate Gapless Playback:** Web Audio schedules nodes on the hardware clock (`audioContext.currentTime`), starting chunk $N+1$ at the exact microsecond chunk $N$ ends, eliminating clicks and pauses.
* **Elimination of Blob URL Churn:** PCM buffers are decoded and passed directly to the audio graph without creating and revoking hundreds of Blob URLs.

### 3.5 Chunk Ladder & Progressive Streaming
* Instead of jumping from 240 chars directly to 800 chars, use a progressive chunk ladder:
  $$\text{Chunk 0: } 240 \text{ chars} \longrightarrow \text{Chunk 1: } 480 \text{ chars} \longrightarrow \text{Chunk 2+: } 800 \text{ chars}$$
  This ensures Chunk 1 arrives before Chunk 0 finishes playing, preventing buffer starvation.
* On the server, introducing `/tts/stream` (chunked HTTP/1.1 or Server-Sent Events) allows streaming PCM audio to the client as each chunk finishes, reducing Time-To-First-Audio (TTFA) to ~250ms regardless of total document length.

---

## 4. Code Simplification & Best Practices (Ponytail Principles)

1. **Delete Dead Code (`client.js`):**
   * `mergeMonoPcmWavs` (lines 204–226): 23 lines of multi-WAV byte merging and RIFF header rewriting that is never called at runtime. Can be removed.
2. **Prune Over-Engineered Abstractions (`client.js`):**
   * `speechChunkLimits` supports multi-format option objects and variable parameters that are never passed. Replaced by idiomatic default arguments.
3. **Consolidate Redundant Validation (`client.js`):**
   * `unwrapAudio` re-validates `audioBase64` and checks `result.ok` after Cordis schema validation has already executed.
4. **Single-Pass String Operations (`ruaccent.rs`):**
   * `delete_spaces_before_punctuation` runs 33 iterative `.replace()` calls per sentence, generating 67 intermediate string allocations. A single-pass character iterator replaces all 33 passes.
5. **Direct Base64 Decoding:**
   * In `client.js`, replace the byte-by-byte `atob()` charCode loop with `Uint8Array.fromBase64()` where supported, eliminating a 16 MB binary string allocation and UI thread freeze.

---

## 5. Prioritized Implementation Roadmap

### Phase 1: Immediate Stability & Resilience (P0) — No DSH Restart Required
* **`dsh-plugin/lib/index.js`:**
  - Implement bounded retry with exponential backoff and jitter (3 attempts) on HTTP 429, 503, and transient network errors (`ECONNRESET`, `ETIMEDOUT`).
  - Fix `TimeoutError` detection in `AbortSignal.timeout` so timeouts are not masked.
  - Increase `timeoutMs` default from 30s to 60s.
  - Strip trailing `/tts` in `validateAndResolveEndpoint` to prevent `/tts/tts` 404 bugs.
* **`dsh-plugin/lib/client.js`:**
  - Do not abort active playback when a background chunk fails; allow buffered chunks to finish playing, and retry failed chunks.
  - Implement the progressive chunk ladder (240 $\rightarrow$ 480 $\rightarrow$ 800) to prevent buffer starvation.
  - Add `Uint8Array.fromBase64` fast path to avoid UI thread GC freezes.
* **`src/num2words.rs`:**
  - Fix the unconditional array out-of-bounds panic for English integers $\ge 2\times 10^{12}$.

### Phase 2: Server Concurrency & Performance (P1) — Applied on Next Server Build
* **`src/server.rs`:**
  - Move `ActiveRequest` lifetime inside `spawn_blocking` so the admission permit is held until worker threads join and engine mutexes are released (fixing the cancellation race condition).
  - Increase queue depth `MAX_ADMITTED_REQUESTS` from 3 to 16.
  - Pre-warm `speechfront` TOML normalizer at startup.
  - Add `.with_graceful_shutdown()` to Axum listener.
* **`src/tera.rs` & `src/wav.rs`:**
  - Preload `style_ttl.npy` and `style_dp.npy` into memory during engine startup.
  - Eliminate the 442 KB clone in `named_output_f32` by borrowing tensor views directly.
  - Implement a 5ms raised-cosine crossfade in `wav.rs` to eliminate chunk seam clicks.

### Phase 3: Infrastructure, Watchdog & Gapless Audio (P2)
* **`deploy/linux/systemd/teratts.service`:**
  - Align thread count to `CPUQuota=400%`: set `TERATTS_ORT_THREADS=2` and `TERATTS_PARALLEL_CHUNKS=2` ($2\times 2=4$ threads).
  - Increase memory headroom to `MemoryHigh=6500M` and `MemoryMax=7500M`.
  - Configure `Type=notify` with `WatchdogSec=30s` and engine `try_lock()` health heartbeats.
* **`dsh-plugin/lib/client.js`:**
  - Migrate playback engine to Web Audio API (`AudioContext`) for sample-accurate gapless playback immune to browser autoplay blocking.
