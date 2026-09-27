import { createHash } from "node:crypto";
import { cleanMarkdown, splitSpeechText } from "./speech-text.js";

// Cancel one waiter without aborting shared work needed by other consumers.
export function waitForSharedJob(promise, signal) {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(signal.reason);
  return new Promise((resolve, reject) => {
    const abort = () => reject(signal.reason);
    signal.addEventListener("abort", abort, { once: true });
    Promise.resolve(promise).then(
      (value) => { signal.removeEventListener("abort", abort); resolve(value); },
      (error) => { signal.removeEventListener("abort", abort); reject(error); },
    );
  });
}

export function normalizeEndpointWithoutAuth(endpointStr) {
  try {
    const u = new URL(typeof endpointStr === "string" ? endpointStr : "http://127.0.0.1:8088");
    return `${u.origin}${u.pathname}`.replace(/\/+$/, "");
  } catch {
    return String(endpointStr || "").replace(/\/+$/, "");
  }
}

export function audioKey(text, config, synthesisRevision = "unknown") {
  const cleanEndpoint = normalizeEndpointWithoutAuth(config?.endpoint);
  return createHash("sha256")
    .update(
      JSON.stringify([
        text,
        config?.voice ?? "ru_f1",
        config?.language ?? "ru",
        config?.stress === true,
        config?.speechFront !== false,
        cleanEndpoint,
        synthesisRevision,
        "v1_140_240_320",
      ]),
    )
    .digest("hex");
}

export function prepareKey(
  messageId,
  rawText,
  inputFormat = "markdown",
  language = "ru",
  endpoint = "",
  preparationRevision = "unknown",
) {
  const cleanEndpoint = normalizeEndpointWithoutAuth(endpoint);
  const textHash = createHash("sha256").update(String(rawText || "")).digest("hex").slice(0, 16);
  return createHash("sha256")
    .update(
      JSON.stringify([
        String(messageId || ""),
        textHash,
        String(inputFormat || "markdown"),
        String(language || "ru"),
        cleanEndpoint,
        String(preparationRevision || "unknown"),
      ]),
    )
    .digest("hex");
}

export class PreparedTextCache {
  constructor(options = {}) {
    this.maxEntries = options.maxEntries ?? 128;
    this.maxBytes = options.maxBytes ?? 16 * 1024 * 1024; // 16 MiB accounted limit
    this.ttlMs = options.ttlMs ?? 15 * 60 * 1000; // 15 minutes
    this.cache = new Map(); // key -> { text, preparationRevision, warnings, createdAt, size }
    this.accountedBytes = 0;
  }

  get entryCount() {
    return this.cache.size;
  }

  get(key, expectedRevision) {
    const entry = this.cache.get(key);
    if (!entry) return undefined;

    if (Date.now() - entry.createdAt > this.ttlMs) {
      this.delete(key);
      return undefined;
    }

    if (expectedRevision && entry.preparationRevision !== expectedRevision) {
      this.delete(key);
      return undefined;
    }

    // Refresh LRU
    this.cache.delete(key);
    this.cache.set(key, entry);

    return {
      text: entry.text,
      preparationRevision: entry.preparationRevision,
      warnings: entry.warnings,
    };
  }

  set(key, value) {
    if (!value || typeof value.text !== "string") return false;

    const entrySize = Buffer.byteLength(value.text, "utf8");
    if (entrySize > this.maxBytes) return false;

    if (this.cache.has(key)) {
      this.delete(key);
    }

    // Evict oldest until within entries and bytes bounds
    while (
      (this.cache.size >= this.maxEntries || this.accountedBytes + entrySize > this.maxBytes) &&
      this.cache.size > 0
    ) {
      const oldestKey = this.cache.keys().next().value;
      this.delete(oldestKey);
    }

    this.cache.set(key, {
      text: value.text,
      preparationRevision: String(value.preparationRevision || "unknown"),
      warnings: Array.isArray(value.warnings) ? value.warnings : [],
      createdAt: Date.now(),
      size: entrySize,
    });
    this.accountedBytes += entrySize;
    return true;
  }

  delete(key) {
    const existing = this.cache.get(key);
    if (existing) {
      this.accountedBytes = Math.max(0, this.accountedBytes - (existing.size || 0));
      this.cache.delete(key);
      return true;
    }
    return false;
  }

  clear() {
    this.cache.clear();
    this.accountedBytes = 0;
  }
}

export class ByteBoundedAudioCache {
  constructor(options = {}) {
    this.maxBytes = options.maxBytes ?? 32 * 1024 * 1024; // 32 MiB
    this.maxEntries = options.maxEntries ?? 64;
    this.maxEntryBytes = options.maxEntryBytes ?? 4 * 1024 * 1024; // 4 MiB
    this.ttlMs = options.ttlMs ?? 10 * 60 * 1000; // 10 minutes

    this.cache = new Map(); // key -> { audioBuffer, mimeType, synthesisRevision, duration, createdAt, size, cacheGeneration }
    this.currentBytes = 0;
    this.generation = 1;
  }

  get entryCount() {
    return this.cache.size;
  }

  get(key, synthesisRevision) {
    this.purgeExpired();
    const entry = this.cache.get(key);
    if (!entry) return undefined;

    if (entry.synthesisRevision !== synthesisRevision) {
      this.delete(key);
      return undefined;
    }

    // Refresh LRU position
    this.cache.delete(key);
    this.cache.set(key, entry);

    return {
      audioBuffer: entry.audioBuffer,
      mimeType: entry.mimeType,
      synthesisRevision: entry.synthesisRevision,
      duration: entry.duration,
    };
  }

  set(key, audio, jobGeneration) {
    if (!audio || !audio.audioBuffer) return false;
    // Late completions from older generations are rejected
    if (jobGeneration !== undefined && jobGeneration < this.generation) {
      return false;
    }

    const size = audio.audioBuffer.byteLength;
    // Entries larger than maxEntryBytes are returned to the caller but not cached
    if (size > this.maxEntryBytes || size > this.maxBytes) {
      return false;
    }

    // Copy buffer slice if it retains a larger backing array buffer
    let storedBuffer = audio.audioBuffer;
    if (storedBuffer.byteLength !== storedBuffer.buffer.byteLength) {
      storedBuffer = Buffer.from(storedBuffer);
    }

    // If key already exists, subtract old size
    if (this.cache.has(key)) {
      this.delete(key);
    }

    // Evict oldest entries by LRU until fits
    while (
      (this.currentBytes + size > this.maxBytes || this.cache.size >= this.maxEntries) &&
      this.cache.size > 0
    ) {
      const oldestKey = this.cache.keys().next().value;
      if (oldestKey !== undefined) this.delete(oldestKey);
      else break;
    }

    const entry = {
      audioBuffer: storedBuffer,
      mimeType: audio.mimeType || "audio/wav",
      synthesisRevision: audio.synthesisRevision,
      duration: audio.duration,
      createdAt: Date.now(),
      size,
      cacheGeneration: this.generation,
    };

    this.cache.set(key, entry);
    this.currentBytes += size;
    return true;
  }

  delete(key) {
    const existing = this.cache.get(key);
    if (existing) {
      this.currentBytes -= existing.size;
      this.cache.delete(key);
      return true;
    }
    return false;
  }

  clear() {
    this.generation += 1;
    this.cache.clear();
    this.currentBytes = 0;
  }

  invalidateRevision(newRevision) {
    this.generation += 1;
    for (const [key, entry] of this.cache.entries()) {
      if (entry.synthesisRevision !== newRevision) {
        this.delete(key);
      }
    }
  }

  purgeExpired() {
    const now = Date.now();
    for (const [key, entry] of this.cache.entries()) {
      if (now - entry.createdAt > this.ttlMs) {
        this.delete(key);
      }
    }
  }
}

export class PlaybackCoordinator {
  constructor(options = {}) {
    this.maxSessions = options.maxSessions ?? 8;

    // Multi-lease registry for tabs: ownerKey -> { ownerId, epoch, until }
    this.activeLeases = new Map();
    this.foregroundRequests = 0;
    this.leaseTimer = null;
    this.disposed = false;

    // Session candidate registry: sessionId -> candidate object
    this.sessionCandidates = new Map();
    this.roundRobinCursor = 0;

    // In-flight execution state
    this.backgroundRunning = 0; // strictly <= 1
    this.currentJob = null; // InFlightJob | null
    this.inFlightJobs = new Map(); // key -> InFlightJob
    this.inFlightPrepares = new Map(); // prepareKey -> { promise, consumers, abortController }
    this.prepareRunning = 0; // strictly <= 1 active prepare request
    this.prepareQueue = new Map(); // key -> { resolve, reject }
    this.prepareStats = {
      requests: 0,
      cacheHits: 0,
      deduplicatedWaiters: 0,
      errors: 0,
      timeouts: 0,
      queueDrops: 0,
      latencies: [],
    };

    // Network defensive state
    this.speculationSuspended = false;
    this.suspensionReason = null;

    // Metadata freshness cache: 30s bounded staleness
    this.metadataFreshnessMs = options.metadataFreshnessMs ?? 30_000;
    this.cachedRevision = null;
    this.cachedRevisionTimestamp = 0;
    this.cachedRevisionEndpoint = null;
    this.revisionFetchJob = null;
  }

  // --- Foreground Lease Management (per tab / owner) ---

  isForegroundActive() {
    const now = Date.now();
    for (const [key, lease] of this.activeLeases) {
      if (lease.until <= now) this.activeLeases.delete(key);
    }
    return this.foregroundRequests > 0 || this.activeLeases.size > 0;
  }

  holdForegroundRequest() {
    if (this.disposed) throw new Error("speech coordinator disposed");
    this.foregroundRequests++;
    let released = false;
    return () => {
      if (released) return;
      released = true;
      this.foregroundRequests--;
      this.pump();
    };
  }

  acquireForeground(ownerId, epoch) {
    if (this.disposed || typeof ownerId !== "string" || !ownerId || ownerId.length > 256 ||
        !Number.isSafeInteger(epoch) || epoch < 0) return { ok: false };
    this.isForegroundActive();
    const previous = this.activeLeases.get(ownerId);
    if ((previous && epoch < previous.epoch) || (!previous && this.activeLeases.size >= 32)) {
      return { ok: false };
    }
    this.activeLeases.set(ownerId, { ownerId, epoch, until: Date.now() + 15_000 });
    this.scheduleLeaseExpiry();
    return { ok: true };
  }

  renewForeground(ownerId, epoch) {
    this.isForegroundActive();
    const lease = this.activeLeases.get(ownerId);
    if (!this.disposed && lease && lease.epoch === epoch) {
      lease.until = Date.now() + 15_000;
      this.scheduleLeaseExpiry();
      return { ok: true };
    }
    return { ok: false };
  }

  scheduleLeaseExpiry() {
    clearTimeout(this.leaseTimer);
    this.leaseTimer = null;
    this.isForegroundActive();
    if (this.disposed || this.activeLeases.size === 0) return;
    const until = Math.min(...Array.from(this.activeLeases.values(), (lease) => lease.until));
    this.leaseTimer = setTimeout(() => {
      this.leaseTimer = null;
      this.isForegroundActive();
      this.scheduleLeaseExpiry();
      this.pump();
    }, Math.max(1, until - Date.now()));
    this.leaseTimer.unref?.();
  }

  dispose() {
    this.disposed = true;
    clearTimeout(this.leaseTimer);
    this.leaseTimer = null;
    this.activeLeases.clear();
    this.dropPendingSpeculation();
    for (const waiter of this.prepareQueue.values()) waiter.reject(new Error("speech coordinator disposed"));
    this.prepareQueue.clear();
    for (const job of this.inFlightPrepares.values()) job.abortController.abort();
    // Transport abort is not proof that native backend computation has stopped.
    this.currentJob?.abortController.abort();
  }

  releaseForeground(ownerId, epoch) {
    const lease = this.activeLeases.get(ownerId);
    if (lease && lease.epoch === epoch) {
      this.activeLeases.delete(ownerId);
      this.scheduleLeaseExpiry();
      if (!this.isForegroundActive()) {
        this.pump();
      }
      return { ok: true };
    }
    return { ok: false };
  }

  // --- Speculation Suspension (BACKEND_OUTCOME_UNKNOWN) ---

  isSpeculationSuspended() {
    return this.speculationSuspended;
  }

  suspendSpeculation(reason) {
    this.speculationSuspended = true;
    this.suspensionReason = String(reason);
  }

  resetSpeculationSuspensionAdmin(reason) {
    this.speculationSuspended = false;
    this.suspensionReason = null;
    this.pump();
  }

  // --- Candidate Queue Management (Round-Robin up to 8 sessions) ---

  scheduleSessionCandidate(sessionId, candidate) {
    if (this.disposed || typeof sessionId !== "string" || !sessionId) return false;

    // Reject 9th session if pool is full and this session is not already registered
    if (!this.sessionCandidates.has(sessionId) && this.sessionCandidates.size >= this.maxSessions) {
      return false;
    }

    // Replace candidate for this session (preserving candidateGeneration logic)
    this.sessionCandidates.set(sessionId, candidate);
    this.pump();
    return true;
  }

  removeSession(sessionId) {
    this.sessionCandidates.delete(sessionId);
  }

  dropPendingSpeculation() {
    this.sessionCandidates.clear();
  }

  // --- Job Registry and Atomic Promotion ---

  getInFlightPrepare(key) {
    return this.inFlightPrepares.get(key);
  }

  schedulePrepareJob(key, consumerId, runFn) {
    if (this.disposed) return Promise.reject(new Error("speech coordinator disposed"));
    this.prepareStats.requests += 1;

    const existing = this.inFlightPrepares.get(key);
    if (existing) {
      this.prepareStats.deduplicatedWaiters += 1;
      if (consumerId) existing.consumers.add(String(consumerId));
      return existing.promise;
    }

    const abortController = new AbortController();
    const consumers = new Set();
    if (consumerId) consumers.add(String(consumerId));

    const promise = (async () => {
      if (this.prepareRunning >= 1) {
        if (this.prepareQueue.size >= 8) {
          const oldest = this.prepareQueue.keys().next().value;
          const dropped = this.prepareQueue.get(oldest);
          this.prepareQueue.delete(oldest);
          this.prepareStats.queueDrops += 1;
          dropped?.reject?.(new Error("prepare queue capacity exceeded"));
        }
        try {
          await new Promise((resolve, reject) => {
            this.prepareQueue.set(key, { resolve, reject });
          });
        } catch (error) {
          // This waiter never owned the execution slot; clean its registry only.
          if (this.inFlightPrepares.get(key)?.promise === promise) {
            this.inFlightPrepares.delete(key);
          }
          throw error;
        }
      }

      this.prepareRunning = 1;
      const t0 = Date.now();
      try {
        if (this.disposed) throw new Error("speech coordinator disposed");
        // Convert a synchronous callback throw to a rejected promise, so registry
        // initialization completes before the finally block observes `promise`.
        const result = await (async () => runFn(abortController.signal))();
        const latency = Date.now() - t0;
        this.prepareStats.latencies.push(latency);
        if (this.prepareStats.latencies.length > 200) {
          this.prepareStats.latencies.shift();
        }
        return result;
      } catch (err) {
        this.prepareStats.errors += 1;
        if (err?.name === "TimeoutError") {
          this.prepareStats.timeouts += 1;
        }
        throw err;
      } finally {
        if (this.inFlightPrepares.get(key)?.promise === promise) {
          this.inFlightPrepares.delete(key);
        }
        if (this.prepareQueue.size > 0) {
          // Transfer the slot without opening an admission gap before the waiter resumes.
          const nextKey = this.prepareQueue.keys().next().value;
          const nextItem = this.prepareQueue.get(nextKey);
          this.prepareQueue.delete(nextKey);
          nextItem?.resolve?.();
        } else {
          this.prepareRunning = 0;
        }
      }
    })();

    this.inFlightPrepares.set(key, { promise, consumers, abortController });
    return promise;
  }

  getInFlightJob(key) {
    return this.inFlightJobs.get(key);
  }

  promoteJob(key, consumerId, cacheGeneration) {
    const job = this.inFlightJobs.get(key);
    if (!job || (cacheGeneration !== undefined && job.cacheGeneration !== cacheGeneration)) return null;

    job.foregroundConsumers.add(String(consumerId));
    return job.promise;
  }

  // --- Dispatcher / Pump ---

  pump() {
    if (this.disposed || this.backgroundRunning >= 1) return;
    if (this.isForegroundActive()) return;
    if (this.isSpeculationSuspended()) return;
    if (this.sessionCandidates.size === 0) return;

    // Round-robin selection of next candidate
    const sessionKeys = Array.from(this.sessionCandidates.keys());
    if (sessionKeys.length === 0) return;

    this.roundRobinCursor = this.roundRobinCursor % sessionKeys.length;
    const selectedSessionId = sessionKeys[this.roundRobinCursor];

    const candidate = this.sessionCandidates.get(selectedSessionId);
    if (!candidate) return;

    // Reserve slot synchronously before any await
    this.backgroundRunning = 1;

    const abortController = new AbortController();
    const jobId = `job_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const job = {
      id: jobId,
      key: candidate.key,
      cacheGeneration: candidate.cacheGeneration,
      abortController,
      foregroundConsumers: new Set(),
      promise: null,
    };

    this.currentJob = job;
    this.inFlightJobs.set(candidate.key, job);

    job.promise = (async () => {
      let isUnknownOutcome = false;
      try {
        if (this.isForegroundActive()) return null;
        const result = await candidate.run(abortController.signal);

        return result;
      } catch (error) {
        // Classify network failure / timeout as BACKEND_OUTCOME_UNKNOWN
        const isNetworkErr =
          error?.backendOutcomeUnknown === true ||
          error?.name === "TimeoutError" ||
          error?.code === "ECONNRESET" ||
          error?.code === "ETIMEDOUT" ||
          error?.code === "ECONNREFUSED" ||
          (error instanceof TypeError && /fetch failed/i.test(error.message));

        if (isNetworkErr && !abortController.signal.aborted) {
          isUnknownOutcome = true;
          this.suspendSpeculation("network_timeout_unknown_outcome");
        }

        // If promoted to foreground, propagate error to foreground consumers
        if (job.foregroundConsumers.size > 0) {
          throw error;
        }
        // Otherwise, background speculative errors are quietly absorbed
        return null;
      } finally {
        // Each candidate gets one dispatch, including on rejection. Retrying an
        // unchanged HTTP failure here would otherwise create an unbounded loop.
        const currentCand = this.sessionCandidates.get(selectedSessionId);
        if (currentCand === candidate) {
          this.sessionCandidates.delete(selectedSessionId);
        } else {
          this.roundRobinCursor = (this.roundRobinCursor + 1) % Math.max(1, this.sessionCandidates.size);
        }
        if (this.currentJob === job) {
          this.currentJob = null;
        }
        if (this.inFlightJobs.get(candidate.key) === job) {
          this.inFlightJobs.delete(candidate.key);
        }
        this.backgroundRunning = 0;
        this.pump();
      }
    })();
  }

  // --- Metadata Freshness (30s Bounded Staleness) ---

  async getOrFetchSynthesisRevision(endpoint) {
    const healthUrl = new URL(endpoint);
    healthUrl.pathname = `${healthUrl.pathname.replace(/\/+$/, "").replace(/\/tts$/, "")}/health`;
    healthUrl.hash = "";
    const endpointKey = healthUrl.toString();
    const now = Date.now();
    if (this.cachedRevisionEndpoint === endpointKey && this.cachedRevision &&
        now - this.cachedRevisionTimestamp < this.metadataFreshnessMs) {
      return this.cachedRevision;
    }
    if (this.revisionFetchJob?.endpoint === endpointKey) return this.revisionFetchJob.promise;

    const job = { endpoint: endpointKey, promise: null };
    this.revisionFetchJob = job;
    job.promise = (async () => {
      try {
        const res = await fetch(endpointKey, { redirect: "error", signal: AbortSignal.timeout(3000) });
        if (!res.ok) return null;
        const data = await res.json();
        if (data && typeof data.synthesis_revision === "string" && data.synthesis_revision.length > 0 &&
            data.synthesis_revision.length <= 256) {
          if (this.revisionFetchJob === job) {
            this.cachedRevision = data.synthesis_revision;
            this.cachedRevisionTimestamp = Date.now();
            this.cachedRevisionEndpoint = endpointKey;
          }
          return data.synthesis_revision;
        }
        return null;
      } catch {
        return null;
      } finally {
        if (this.revisionFetchJob === job) this.revisionFetchJob = null;
      }
    })();
    return job.promise;
  }
}

export function messageRawText(session, messageId) {
  if (!session || typeof session.deriveMessages !== "function") return null;
  const message = session.deriveMessages().find((item) => item.id === messageId && item.role === "assistant");
  if (!message) return null;
  const text = message.content
    ?.filter((block) => block.type === "text")
    ?.map((block) => block.text)
    ?.join("\n");
  if (!text || text.length > 100_000) return null;
  return text;
}

export function messageFirstChunk(session, messageId) {
  if (!session || typeof session.deriveMessages !== "function") return null;
  const message = session.deriveMessages().find((item) => item.id === messageId && item.role === "assistant");
  if (!message) return null;
  const text = message.content
    ?.filter((block) => block.type === "text")
    ?.map((block) => block.text)
    ?.join("\n");
  if (!text || text.length > 100_000) return null;
  const cleaned = cleanMarkdown(text);
  if (!cleaned) return null;
  const chunks = splitSpeechText(cleaned);
  return chunks.length > 0 ? chunks[0] : null;
}
