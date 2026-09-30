import { Buffer } from "node:buffer";
import { randomUUID } from "node:crypto";
import { PrivateTelemetry } from "./private-telemetry.js";
import s from "@deepseek-ai/schemastery";
import { credentialRef } from "@deepseek-ai/dsh-credentials";
import { Remote, TypertRemoteService } from "@deepseek-ai/dsh-typert-protocol";
import { cleanMarkdown, splitSpeechText } from "./speech-text.js";
import {
  ByteBoundedAudioCache,
  PlaybackCoordinator,
  PreparedTextCache,
  audioKey,
  prepareKey,
  messageFirstChunk,
  messageRawText,
  normalizeEndpointWithoutAuth,
  waitForSharedJob,
} from "./coordinator.js";

const DEFAULT_TOKEN_REF = "TERATTS_TOKEN";
export const MAX_RESPONSE_BYTES = 16 * 1024 * 1024; // 16 MiB

export const Config = s.object({
  endpoint: s.string().default("http://127.0.0.1:8088"),
  telemetryIngest: s.string().default(""),
  timeoutMs: s.number().step(1).min(1).default(60_000),
  maxRetries: s.number().step(1).min(0).max(10).default(3),
  voice: s.string().default("ru_f1"),
  language: s.string().default("ru"),
  stress: s.boolean().default(false),
  speechFront: s.boolean().default(true),
  tokenEnv: s.string().role("credential-ref").default(DEFAULT_TOKEN_REF),
  prepareMode: s.string().default("off"),
});

function isLoopbackHost(hostname) {
  if (
    hostname === "localhost" ||
    hostname === "127.0.0.1" ||
    hostname === "::1" ||
    hostname === "[::1]"
  ) {
    return true;
  }
  if (/^127(?:\.\d{1,3}){3}$/.test(hostname)) {
    const parts = hostname.split(".").map(Number);
    return parts.every((p) => p >= 0 && p <= 255);
  }
  return false;
}

export function validateAndResolveEndpoint(endpointConfig) {
  let parsed;
  try {
    parsed = new URL(endpointConfig);
  } catch {
    throw new Error("Invalid TeraTTS endpoint URL");
  }

  const protocol = parsed.protocol;
  const hostname = parsed.hostname.toLowerCase();

  const isHttpLoopback = protocol === "http:" && isLoopbackHost(hostname);
  const isHttpsTailnet = protocol === "https:" && hostname === "teratts.tail9fd337.ts.net";

  if (!isHttpLoopback && !isHttpsTailnet) {
    throw new Error("TeraTTS endpoint is not allowed");
  }

  const basePath = parsed.pathname.replace(/\/+$/, "").replace(/\/tts$/, "");
  parsed.pathname = `${basePath}/tts`;
  return parsed.toString();
}

export function validateAndResolvePrepareEndpoint(endpointConfig) {
  const ttsUrl = new URL(validateAndResolveEndpoint(endpointConfig));
  const basePath = ttsUrl.pathname.replace(/\/+$/, "").replace(/\/tts$/, "");
  ttsUrl.pathname = `${basePath}/prepare`;
  return ttsUrl.toString();
}

function parseRetryAfter(response, errorBody) {
  let retryAfterMs;
  const retryAfterHeader = response.headers.get("retry-after");
  if (retryAfterHeader) {
    const seconds = Number.parseFloat(retryAfterHeader);
    if (Number.isFinite(seconds) && seconds >= 0) {
      retryAfterMs = Math.round(seconds * 1000);
    } else {
      const dateMs = Date.parse(retryAfterHeader);
      if (!Number.isNaN(dateMs)) {
        retryAfterMs = Math.max(0, dateMs - Date.now());
      }
    }
  }

  if (typeof errorBody === "object" && errorBody !== null) {
    if (Number.isFinite(errorBody.retry_after_ms) && errorBody.retry_after_ms >= 0) {
      retryAfterMs = errorBody.retry_after_ms;
    } else if (Number.isFinite(errorBody.retry_after) && errorBody.retry_after >= 0) {
      retryAfterMs = Math.round(errorBody.retry_after * 1000);
    }
  }

  return retryAfterMs;
}

async function readErrorResponse(response) {
  if (!response.body?.getReader) return null;
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 4096) {
        await reader.cancel();
        return null;
      }
      chunks.push(value);
    }
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    return null;
  } finally {
    reader.releaseLock?.();
  }
}

function isRetryableStatus(status) {
  return status === 429 || status === 503;
}

function isRetryableNetworkError(error) {
  if (error?.name === "AbortError" || error?.name === "TimeoutError") return false;
  const code = error?.code || error?.cause?.code;
  if (
    code === "ECONNRESET" ||
    code === "ETIMEDOUT" ||
    code === "ECONNREFUSED" ||
    code === "EPIPE" ||
    code === "EAI_AGAIN" ||
    code === "ENOTFOUND" ||
    code === "UND_ERR_SOCKET" ||
    code === "UND_ERR_CONNECT_TIMEOUT"
  ) {
    return true;
  }
  return error instanceof TypeError && /fetch failed/i.test(error.message);
}

function computeBackoffDelay(attempt, retryAfterMs, baseDelayMs = 500, maxDelayMs = 5000) {
  if (typeof retryAfterMs === "number" && retryAfterMs > 0) {
    return retryAfterMs + Math.floor(Math.random() * 250);
  }
  const maxBackoff = Math.min(maxDelayMs, baseDelayMs * (2 ** attempt));
  return Math.floor(Math.random() * maxBackoff);
}

function sleepWithSignal(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(signal.reason);
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    function onAbort() {
      clearTimeout(timer);
      reject(signal.reason);
    }
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

async function readAudioResponse(response) {
  const contentLengthHeader = response.headers.get("content-length");
  if (contentLengthHeader !== null) {
    const contentLength = Number.parseInt(contentLengthHeader, 10);
    if (!Number.isNaN(contentLength) && contentLength > MAX_RESPONSE_BYTES) {
      throw new Error("TeraTTS response size exceeded 16 MiB limit");
    }
  }

  let audio;
  if (response.body && typeof response.body.getReader === "function") {
    const reader = response.body.getReader();
    const chunks = [];
    let totalBytes = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        totalBytes += value.byteLength;
        if (totalBytes > MAX_RESPONSE_BYTES) {
          await reader.cancel();
          throw new Error("TeraTTS response size exceeded 16 MiB limit");
        }
        chunks.push(value);
      }
    } catch (err) {
      if (
        err?.name === "AbortError" ||
        err?.name === "TimeoutError" ||
        (err?.message && err.message.includes("16 MiB limit"))
      ) {
        throw err;
      }
      throw new Error("TeraTTS failed to read audio response");
    }
    audio = Buffer.concat(chunks);
  } else {
    const arrayBuffer = await response.arrayBuffer();
    if (arrayBuffer.byteLength > MAX_RESPONSE_BYTES) {
      throw new Error("TeraTTS response size exceeded 16 MiB limit");
    }
    audio = Buffer.from(arrayBuffer);
  }

  if (audio.length === 0) {
    throw new Error("TeraTTS returned empty audio");
  }

  return audio;
}

const remoteInitializers = [];

export class TeraTtsVoiceService extends TypertRemoteService {
  constructor(ctx, current) {
    super(ctx, "terattsVoice");
    this.current = current;
    this.telemetry = new PrivateTelemetry(current().telemetryIngest);
    this.cache = new ByteBoundedAudioCache();
    this.preparedTextCache = new PreparedTextCache();
    this.coordinator = new PlaybackCoordinator();
    this.foregroundJobs = new Map();
    this.synthesisRevision = "unknown";
    this.preparationRevision = "unknown";

    for (const initialize of remoteInitializers) initialize.call(this);
  }

  async acquireForeground(ownerId, epoch) {
    return this.coordinator.acquireForeground(ownerId, epoch);
  }

  async renewForeground(ownerId, epoch) {
    return this.coordinator.renewForeground(ownerId, epoch);
  }

  async releaseForeground(ownerId, epoch) {
    return this.coordinator.releaseForeground(ownerId, epoch);
  }

  async prepareConfigured(text, signal, config) {
    validateAndResolveEndpoint(config.endpoint);
    const endpoint = validateAndResolvePrepareEndpoint(config.endpoint);
    const timeout = AbortSignal.timeout(Math.min(config.timeoutMs ?? 60_000, 10_000));
    const requestSignal = signal ? AbortSignal.any([signal, timeout]) : timeout;

    const credentials = this.ctx.get("credentials");
    let tokenValue;
    if (credentials) {
      try {
        const token = await credentials.resolve(credentialRef(config.tokenEnv));
        tokenValue = token?.value;
      } catch (err) {
        console.warn(`[teratts] failed to resolve credential ${config.tokenEnv}:`, err);
      }
    }
    if (!tokenValue && typeof process !== "undefined" && process.env) {
      tokenValue = process.env[config.tokenEnv];
    }

    const requestPayload = JSON.stringify({
      text,
      input_format: "markdown",
      language: config.language === "en" ? "en" : "ru",
    });

    const headers = {
      "content-type": "application/json",
      ...(tokenValue ? { authorization: `Bearer ${tokenValue}` } : {}),
    };

    let response;
    try {
      response = await fetch(endpoint, {
        method: "POST",
        redirect: "error",
        headers,
        body: requestPayload,
        signal: requestSignal,
      });
    } catch (error) {
      console.warn(`[teratts] prepare fetch failed:`, error);
      throw error;
    }

    if (!response.ok) {
      throw new Error(`TeraTTS prepare failed with HTTP ${response.status}`);
    }

    const data = await response.json();
    return {
      text: typeof data.text === "string" ? data.text : "",
      preparationRevision: typeof data.preparation_revision === "string" ? data.preparation_revision : "unknown",
      warnings: Array.isArray(data.warnings) ? data.warnings : [],
    };
  }

  async prepareText(rawMarkdown, messageId, messageRevision = "1", signal, consumerId) {
    const config = this.current();
    const mode = config.prepareMode || "off";

    if (mode === "off") {
      return null;
    }

    const key = prepareKey(
      messageId,
      rawMarkdown,
      "markdown",
      config.language,
      config.endpoint,
      this.preparationRevision,
    );

    // 1. Check cached prepared text
    const cached = this.preparedTextCache.get(key, this.preparationRevision);
    if (cached) {
      this.coordinator.prepareStats.cacheHits += 1;
      return cached;
    }

    // 2. Schedule or join in-flight prepare job
    try {
      const result = await this.coordinator.schedulePrepareJob(key, consumerId, async (jobSignal) => {
        const effectiveSignal = signal ? AbortSignal.any([signal, jobSignal]) : jobSignal;
        const outcome = await this.prepareConfigured(rawMarkdown, effectiveSignal, config);
        if (outcome?.preparationRevision && outcome.preparationRevision !== this.preparationRevision) {
          this.preparationRevision = outcome.preparationRevision;
        }
        this.preparedTextCache.set(key, outcome);
        return outcome;
      });
      return result;
    } catch (err) {
      console.warn(`[teratts] prepareText error:`, err);
      return null;
    }
  }

  async recordTelemetry(event) {
    const data = event && typeof event === "object" ? event : {};
    return this.telemetry.record({ ...data, kind: "voice_client_event", host_received_at_ms: Date.now() });
  }

  async synthesizeObserved(text, context, signal) {
    const requestId = randomUUID();
    const trace = { ...context, requestId };
    void this.recordTelemetry({ event: "synthesis_requested", ...trace, submittedText: text });
    signal?.throwIfAborted();
    const release = this.coordinator.holdForegroundRequest();
    try {
      const result = await this.synthesizeForeground(text, signal, trace);
      void this.telemetry.record({ kind: "tts_client_result", ...trace,
        submittedText: text, synthesisRevision: result.synthesisRevision,
        cacheHit: result.telemetryCacheHit === true, origin: result.telemetryOrigin ?? "foreground_or_shared",
        syntheticAudio: true },
        { "synthesized.wav": Buffer.from(result.audioBase64, "base64") });
      return result;
    } catch (error) {
      void this.recordTelemetry({ event: "synthesis_failed", ...trace,
        error: error instanceof Error ? error.message : String(error) });
      throw error;
    } finally {
      release();
    }
  }

  async synthesize(text, signal) {
    signal?.throwIfAborted();
    const release = this.coordinator.holdForegroundRequest();
    try {
      return await this.synthesizeForeground(text, signal);
    } finally {
      release();
    }
  }

  async synthesizeForeground(text, signal, telemetryContext) {
    if (typeof text !== "string" || text.trim().length === 0) {
      throw new TypeError("TeraTTS text must not be empty");
    }

    const config = { ...this.current() };

    // Validate/refresh revision with 30s bounded staleness
    validateAndResolveEndpoint(config.endpoint);
    const freshRevision = await waitForSharedJob(this.coordinator.getOrFetchSynthesisRevision(config.endpoint), signal);
    signal?.throwIfAborted();
    if (freshRevision && freshRevision !== this.synthesisRevision) {
      this.synthesisRevision = freshRevision;
      this.cache.invalidateRevision(freshRevision);
    }

    const key = audioKey(text, config, this.synthesisRevision);

    // 1. Check if matching job is currently in flight -> promote it to foreground
    const consumerId = `req_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    const promotedPromise = this.coordinator.promoteJob(key, consumerId, this.cache.generation);
    if (promotedPromise) {
      // A failed shared request is not permission to submit another synthesis:
      // a transport failure may leave native backend computation running.
      const audioResult = await waitForSharedJob(promotedPromise, signal);
      signal?.throwIfAborted();
      if (audioResult && audioResult.audioBuffer) {
        return {
          audioBase64: audioResult.audioBuffer.toString("base64"),
          telemetryCacheHit: true,
          telemetryOrigin: "promoted_prefetch",
          mimeType: audioResult.mimeType || "audio/wav",
        };
      }
    }

    // 2. Check LRU cache (returns Buffer if hit and revision matches)
    const cached = this.cache.get(key, this.synthesisRevision);
    if (cached && cached.audioBuffer) {
      return {
        audioBase64: cached.audioBuffer.toString("base64"),
        telemetryCacheHit: true,
        mimeType: cached.mimeType || "audio/wav",
      };
    }

    // 3. Share foreground work too, not just speculative work. A cancelled
    // consumer stops waiting; the bounded in-flight fragment drains safely.
    const audioResult = await waitForSharedJob(this.foregroundAudio(text, config, key, telemetryContext), signal);
    signal?.throwIfAborted();
    return {
      audioBase64: audioResult.audioBuffer.toString("base64"),
      mimeType: audioResult.mimeType,
    };
  }

  storeAudio(text, config, result, generation) {
    if (generation !== this.cache.generation) return;
    if (result.synthesisRevision && result.synthesisRevision !== this.synthesisRevision) {
      this.synthesisRevision = result.synthesisRevision;
      this.cache.invalidateRevision(result.synthesisRevision);
    }
    this.cache.set(audioKey(text, config, this.synthesisRevision), result, this.cache.generation);
  }

  foregroundAudio(text, config, key, telemetryContext) {
    // A settings reset is a new admission generation even when text/voice match.
    const jobKey = `${this.cache.generation}:${key}`;
    const existing = this.foregroundJobs.get(jobKey);
    if (existing) return existing.promise;
    if (this.foregroundJobs.size >= 16) throw new Error("TeraTTS foreground capacity exceeded");
    const currentGeneration = this.cache.generation;
    const release = this.coordinator.holdForegroundRequest();
    const controller = new AbortController();
    const job = { controller, promise: null };
    this.foregroundJobs.set(jobKey, job);
    job.promise = Promise.resolve().then(async () => {
      const result = await this.synthesizeConfigured(text, controller.signal, config, key, telemetryContext);
      this.storeAudio(text, config, result, currentGeneration);
      return result;
    }).catch((error) => {
      if (error?.backendOutcomeUnknown || error?.name === "TimeoutError") {
        this.coordinator.suspendSpeculation("foreground_backend_outcome_unknown");
      }
      throw error;
    }).finally(() => {
      if (this.foregroundJobs.get(jobKey) === job) this.foregroundJobs.delete(jobKey);
      release();
    });
    return job.promise;
  }

  async synthesizeConfigured(text, signal, config, key, telemetryContext) {
    const language = config.language === "en" ? "en" : "ru";
    const endpoint = validateAndResolveEndpoint(config.endpoint);
    const maxRetries = config.maxRetries ?? 3;

    const timeout = AbortSignal.timeout(config.timeoutMs);
    const requestSignal = signal ? AbortSignal.any([signal, timeout]) : timeout;

    const credentials = this.ctx.get("credentials");
    let tokenValue;
    if (credentials) {
      try {
        const token = await credentials.resolve(credentialRef(config.tokenEnv));
        tokenValue = token?.value;
      } catch (err) {
        console.warn(`[teratts] failed to resolve credential ${config.tokenEnv}:`, err);
      }
    }
    if (!tokenValue && typeof process !== "undefined" && process.env) {
      tokenValue = process.env[config.tokenEnv];
    }

    const requestPayload = JSON.stringify({
      text,
      voice: config.voice,
      language,
      russian_stress: config.stress === true,
      speech_front: config.speechFront !== false,
      duration_scale: 1,
      input_format: "plain",
    });

    const headers = {
      "content-type": "application/json",
      ...(tokenValue ? { authorization: `Bearer ${tokenValue}` } : {}),
    };

    if (telemetryContext?.requestId) headers["x-request-id"] = telemetryContext.requestId;
    for (const [field, name] of [["sessionId", "x-session-id"], ["messageId", "x-message-id"]]) {
      if (typeof telemetryContext?.[field] === "string") headers[name] = telemetryContext[field];
    }
    let lastError = null;

    for (let attempt = 0; attempt <= maxRetries; attempt += 1) {
      if (requestSignal.aborted) {
        throw requestSignal.reason;
      }

      let response;
      try {
        response = await fetch(endpoint, {
          method: "POST",
          redirect: "error",
          headers,
          body: requestPayload,
          signal: requestSignal,
        });
      } catch (error) {
        console.error("[teratts] synthesis transport failed");
        if (signal?.aborted) throw signal.reason;
        if (timeout.aborted || error?.name === "TimeoutError") throw error;
        if (error?.name === "AbortError") throw error;
        const failure = new Error("TeraTTS request failed");
        failure.backendOutcomeUnknown = isRetryableNetworkError(error);
        throw failure;
      }

      if (!response.ok) {
        const errorBody = await readErrorResponse(response);

        const retryAfterMs = parseRetryAfter(response, errorBody);
        console.error(`[teratts] request failed with HTTP ${response.status}:`, {
          status: response.status,
          retryAfterMs,
        });

        const retrySuffix =
          retryAfterMs !== undefined
            ? ` (retry after ${Math.ceil(retryAfterMs / 1000)}s)`
            : "";
        const httpError = new Error(`TeraTTS request failed with HTTP ${response.status}${retrySuffix}`);
        if (retryAfterMs !== undefined) {
          httpError.retryAfterMs = retryAfterMs;
          httpError.retry_after_ms = retryAfterMs;
        }
        httpError.status = response.status;
        httpError.backendOutcomeUnknown = response.status === 502 || response.status === 504;
        lastError = httpError;

        // Retry only explicit admission rejection, never an ambiguous proxy or
        // inference failure that may still own the native backend slot.
        const rejectedBeforeInference = response.status === 429 ||
          (response.status === 503 && errorBody?.code === "queue_timeout");
        if (attempt < maxRetries && isRetryableStatus(response.status) && rejectedBeforeInference) {
          const delayMs = computeBackoffDelay(attempt, retryAfterMs);
          await sleepWithSignal(delayMs, requestSignal);
          continue;
        }

        throw httpError;
      }

      const revHeader = response.headers.get("x-teratts-synthesis-revision") || this.synthesisRevision;
      const audio = await readAudioResponse(response);
      return {
        audioBuffer: audio,
        mimeType: response.headers.get("content-type")?.split(";", 1)[0] || "audio/wav",
        synthesisRevision: revHeader,
      };
    }

    throw lastError || new Error("TeraTTS request failed");
  }
}

for (const method of ["synthesize", "synthesizeObserved", "recordTelemetry", "acquireForeground", "renewForeground", "releaseForeground"]) {
  Remote(method)(TeraTtsVoiceService.prototype[method], {
    kind: "method",
    name: method,
    static: false,
    private: false,
    addInitializer(initializer) {
      remoteInitializers.push(initializer);
    },
  });
}

export const inject = [];

export function preparationListener(service, current) {
  const sessionGenerations = new WeakMap(); // session object -> generation
  const candidateTurns = new WeakMap();

  return async (session, event) => {
    if (session.header?.origin === "subagent") return;
    const sessionId = session.id;
    if (!sessionId) return;

    if (event.type === "session/remove") {
      service.coordinator.removeSession(sessionId);
      sessionGenerations.delete(session);
      candidateTurns.delete(session);
      return;
    }

    if (event.type === "turn/start") {
      candidateTurns.delete(session);
      service.coordinator.removeSession(sessionId);
      sessionGenerations.set(session, (sessionGenerations.get(session) ?? 0) + 1);
      return;
    }

    if (event.type === "assistant/message") {
      candidateTurns.delete(session);
      const { message, turn, interrupted } = event.data;
      if (
        !interrupted &&
        message.content.some((block) => block.type === "text") &&
        !message.content.some((block) => block.type === "tool-call")
      ) {
        candidateTurns.set(session, { turn, messageId: message.id });
      }
      return;
    }

    if (event.type !== "turn/end") return;
    const candidateData = candidateTurns.get(session);
    candidateTurns.delete(session);
    if (event.data.reason?.kind !== "completed" || candidateData?.turn !== event.data.turn) return;

    try {
      const rawText = messageRawText(session, candidateData.messageId);
      if (!rawText) return;

      const oldCleaned = cleanMarkdown(rawText);
      if (!oldCleaned) return;
      const oldChunks = splitSpeechText(oldCleaned);
      if (oldChunks.length === 0) return;
      const oldChunk0 = oldChunks[0];

      const config = { ...current() };
      const mode = config.prepareMode || "off";

      if (mode === "shadow") {
        const t0 = Date.now();
        service.prepareText(rawText, candidateData.messageId, "1", null, `shadow_${sessionId}`)
          .then((prep) => {
            if (prep && typeof prep.text === "string") {
              const prepMs = Date.now() - t0;
              const newChunks = splitSpeechText(prep.text);
              const newChunk0 = newChunks[0] || "";
              console.log("[teratts] shadow prepare:", {
                messageId: candidateData.messageId,
                old_clean_length: oldCleaned.length,
                new_prepare_length: prep.text.length,
                difference_detected: oldCleaned !== prep.text,
                old_chunk_count: oldChunks.length,
                new_chunk_count: newChunks.length,
                first_chunk_match: oldChunk0 === newChunk0,
                prepare_ms: prepMs,
                preparation_revision: prep.preparationRevision,
              });
            }
          })
          .catch((err) => {
            console.warn("[teratts] shadow prepare failed:", err);
          });
      }

      if (service.coordinator.isForegroundActive()) return;
      const nextGen = (sessionGenerations.get(session) ?? 0) + 1;
      sessionGenerations.set(session, nextGen);
      const preparationGeneration = service.cache.generation;
      validateAndResolveEndpoint(config.endpoint);
      const revision = await service.coordinator.getOrFetchSynthesisRevision(config.endpoint);
      if (sessionGenerations.get(session) !== nextGen || service.coordinator.isForegroundActive() ||
          preparationGeneration !== service.cache.generation) return;
      if (revision && revision !== service.synthesisRevision) {
        service.synthesisRevision = revision;
        service.cache.invalidateRevision(revision);
      }
      const firstChunk = oldChunk0;
      const key = audioKey(firstChunk, config, service.synthesisRevision);

      // If already cached or lease is active, skip scheduling
      if (service.cache.get(key, service.synthesisRevision) || service.coordinator.isForegroundActive()) {
        return;
      }

      const candidateCacheGeneration = service.cache.generation;
      service.coordinator.scheduleSessionCandidate(sessionId, {
        sessionId,
        messageId: candidateData.messageId,
        candidateGeneration: nextGen,
        cacheGeneration: candidateCacheGeneration,
        key,
        text: firstChunk,
        config,
        run: async (signal) => {
          if (candidateCacheGeneration !== service.cache.generation ||
              service.coordinator.isForegroundActive() || service.cache.get(key, service.synthesisRevision)) {
            return null;
          }
          const result = await service.synthesizeConfigured(firstChunk, signal, { ...config, maxRetries: 0 }, key);
          service.storeAudio(firstChunk, config, result, candidateCacheGeneration);
          return result;
        },
      });
    } catch {
      // Discard background preparation errors
    }
  };
}

export function apply(ctx, config = {}) {
  const base = {
    endpoint: config.endpoint ?? "http://127.0.0.1:8088",
    timeoutMs: config.timeoutMs ?? 60_000,
    maxRetries: config.maxRetries ?? 3,
    voice: config.voice ?? "ru_f1",
    language: config.language ?? "ru",
    stress: config.stress ?? false,
    speechFront: config.speechFront ?? true,
    tokenEnv: config.tokenEnv ?? DEFAULT_TOKEN_REF,
    prepareMode: config.prepareMode ?? "off",
    telemetryIngest: config.telemetryIngest ?? "",
  };
  // DSH 0.2 reads ordinary Config from the Loader; configuration changes remount
  // this instance, disposing its caches and in-flight work with the old config.
  const current = () => base;
  const service = new TeraTtsVoiceService(ctx, current);
  ctx.effect(() => () => {
    service.coordinator.dispose();
    for (const job of service.foregroundJobs.values()) job.controller.abort();
  });

  const onSessionEvent = preparationListener(service, () => current());
  ctx.on("session/event", (session, event) => {
    // Speculative metadata must not delay the Host's session-event pipeline.
    void onSessionEvent(session, event).catch(() => {});
  });
}
