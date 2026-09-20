import { Buffer } from "node:buffer";
import { createHash } from "node:crypto";
import s from "@deepseek-ai/schemastery";
import { credentialRef } from "@deepseek-ai/dsh-credentials";
import { installSettingsSection, settingsNamespace } from "@deepseek-ai/dsh-settings";
import { Remote, TypertRemoteService } from "@deepseek-ai/dsh-typert-protocol";
import { cleanMarkdown, splitSpeechText } from "./speech-text.js";

const SETTINGS_NAMESPACE = settingsNamespace("teratts");
const DEFAULT_TOKEN_REF = "TERATTS_TOKEN";
export const MAX_RESPONSE_BYTES = 16 * 1024 * 1024; // 16 MiB

export const Config = s.object({
  endpoint: s.string().default("http://127.0.0.1:8088"),
  timeoutMs: s.number().step(1).min(1).default(60_000),
  maxRetries: s.number().step(1).min(0).max(10).default(3),
  voice: s.string().default("ru_f1"),
  language: s.string().default("ru"),
  stress: s.boolean().default(false),
  speechFront: s.boolean().default(true),
  tokenEnv: s.string().role("credential-ref").default(DEFAULT_TOKEN_REF),
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

export function normalizeEndpointWithoutAuth(endpointStr) {
  try {
    const u = new URL(endpointConfigSafe(endpointStr));
    return `${u.origin}${u.pathname}`.replace(/\/+$/, "");
  } catch {
    return String(endpointStr || "").replace(/\/+$/, "");
  }
}

function endpointConfigSafe(endpoint) {
  if (typeof endpoint === "string") return endpoint;
  return "http://127.0.0.1:8088";
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

function isRetryableStatus(status) {
  return status === 429 || status === 503 || status === 502 || status === 504;
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

export class AudioCache {
  constructor(maxItems = 64) {
    this.maxItems = maxItems;
    this.cache = new Map();
    this.inFlight = new Map();
  }

  get(key) {
    const value = this.cache.get(key);
    if (value !== undefined) {
      this.cache.delete(key);
      this.cache.set(key, value);
      return value;
    }
    return undefined;
  }

  set(key, value) {
    if (this.cache.has(key)) {
      this.cache.delete(key);
    } else if (this.cache.size >= this.maxItems) {
      const oldestKey = this.cache.keys().next().value;
      if (oldestKey !== undefined) this.cache.delete(oldestKey);
    }
    this.cache.set(key, value);
  }

  clear() {
    this.cache.clear();
    this.inFlight.clear();
  }
}

export class PlaybackCoordinator {
  constructor() {
    this.activeOwnerId = null;
    this.activeEpoch = null;
    this.activeUntil = 0;

    this.backgroundRunning = 0; // <= 1
    this.backgroundPending = null; // <= 1
    this.currentBackgroundTask = null; // { key, isForeground, abortController, promise }
  }

  isForegroundActive() {
    // Strict invariant: while an unreleased ownerId exists, treat as active/unknown
    // to strictly prevent speculative background synthesis.
    return this.activeOwnerId !== null;
  }

  acquireForeground(ownerId, epoch) {
    this.activeOwnerId = String(ownerId);
    this.activeEpoch = Number(epoch);
    this.activeUntil = Date.now() + 15_000;
    this.backgroundPending = null;
    return { ok: true };
  }

  renewForeground(ownerId, epoch) {
    if (this.activeOwnerId === String(ownerId) && this.activeEpoch === Number(epoch)) {
      this.activeUntil = Date.now() + 15_000;
      return { ok: true };
    }
    return { ok: false };
  }

  releaseForeground(ownerId, epoch) {
    if (this.activeOwnerId === String(ownerId) && this.activeEpoch === Number(epoch)) {
      this.activeOwnerId = null;
      this.activeEpoch = null;
      this.activeUntil = 0;
      this.pumpBackground();
      return { ok: true };
    }
    return { ok: false };
  }

  scheduleBackground(candidate) {
    // A new candidate replaces backgroundPending (bounded to <= 1)
    this.backgroundPending = candidate;
    this.pumpBackground();
  }

  pumpBackground() {
    if (this.backgroundRunning >= 1) return;
    if (this.isForegroundActive()) return;
    if (!this.backgroundPending) return;

    const candidate = this.backgroundPending;
    this.backgroundPending = null;

    // Reserve slot synchronously before any await
    this.backgroundRunning = 1;
    const abortController = new AbortController();
    const task = {
      key: candidate.key,
      isForeground: false,
      abortController,
      promise: null,
    };
    this.currentBackgroundTask = task;

    task.promise = (async () => {
      try {
        if (this.isForegroundActive()) return;
        await candidate.run(abortController.signal);
      } catch {
        // Discard background errors
      } finally {
        if (this.currentBackgroundTask === task) {
          this.currentBackgroundTask = null;
        }
        this.backgroundRunning = 0;
        this.pumpBackground();
      }
    })();
  }

  promoteToForeground(key) {
    if (this.currentBackgroundTask && this.currentBackgroundTask.key === key) {
      this.currentBackgroundTask.isForeground = true;
      return this.currentBackgroundTask.promise;
    }
    return null;
  }

  cancelBackground(reason) {
    this.backgroundPending = null;
    if (this.currentBackgroundTask && !this.currentBackgroundTask.isForeground) {
      this.currentBackgroundTask.abortController.abort(
        reason instanceof Error ? reason : new Error(reason || "Cancelled by foreground"),
      );
    }
  }
}

const remoteInitializers = [];

export class TeraTtsVoiceService extends TypertRemoteService {
  constructor(ctx, current) {
    super(ctx, "terattsVoice");
    this.current = current;
    this.cache = new AudioCache();
    this.coordinator = new PlaybackCoordinator();
    this.synthesisRevision = "unknown";

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

  async synthesize(text, signal) {
    if (typeof text !== "string" || text.trim().length === 0) {
      throw new TypeError("TeraTTS text must not be empty");
    }

    const config = this.current();
    const key = audioKey(text, config, this.synthesisRevision);

    // 1. If this exact key is currently being computed in background, promote it
    const promotedPromise = this.coordinator.promoteToForeground(key);
    if (promotedPromise) {
      try {
        await promotedPromise;
      } catch {
        // If background failed, proceed to foreground fetch
      }
    } else {
      // Manual playback of a different text cancels background in-flight tasks
      this.coordinator.cancelBackground("manual_play");
    }

    // 2. Check LRU cache
    const cached = this.cache.get(key);
    if (cached) {
      return cached;
    }

    // 3. Deduplicate in-flight fetch for the exact same key
    let inFlight = this.cache.inFlight.get(key);
    if (!inFlight) {
      inFlight = this.synthesizeConfigured(text, signal, config, key);
      this.cache.inFlight.set(key, inFlight);
    }

    try {
      const result = await inFlight;
      this.cache.set(key, result);
      return result;
    } finally {
      this.cache.inFlight.delete(key);
    }
  }

  async synthesizeConfigured(text, signal, config, key) {
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
    });

    const headers = {
      "content-type": "application/json",
      ...(tokenValue ? { authorization: `Bearer ${tokenValue}` } : {}),
    };

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
        console.error(`[teratts] fetch to ${endpoint} failed:`, error);
        if (signal?.aborted) throw signal.reason;
        if (timeout.aborted || error?.name === "TimeoutError") throw error;
        if (error?.name === "AbortError") throw error;

        if (attempt < maxRetries && isRetryableNetworkError(error)) {
          lastError = error;
          const delayMs = computeBackoffDelay(attempt, undefined);
          await sleepWithSignal(delayMs, requestSignal);
          continue;
        }

        throw new Error("TeraTTS request failed");
      }

      if (!response.ok) {
        let errorBody = null;
        try {
          const rawText = await response.text();
          if (rawText) {
            try {
              errorBody = JSON.parse(rawText);
            } catch {
              errorBody = rawText;
            }
          }
        } catch {
          // Non-fatal if body cannot be read
        }

        const retryAfterMs = parseRetryAfter(response, errorBody);
        console.error(`[teratts] request failed with HTTP ${response.status}:`, {
          endpoint,
          status: response.status,
          retryAfterMs,
          body: errorBody,
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
        lastError = httpError;

        if (attempt < maxRetries && isRetryableStatus(response.status)) {
          const delayMs = computeBackoffDelay(attempt, retryAfterMs);
          await sleepWithSignal(delayMs, requestSignal);
          continue;
        }

        throw httpError;
      }

      // Check revision header for cache invalidation
      const revHeader = response.headers.get("x-teratts-synthesis-revision");
      if (revHeader && revHeader !== this.synthesisRevision) {
        this.synthesisRevision = revHeader;
        this.cache.clear();
      }

      const audio = await readAudioResponse(response);
      return {
        audioBase64: audio.toString("base64"),
        mimeType: response.headers.get("content-type")?.split(";", 1)[0] || "audio/wav",
      };
    }

    throw lastError || new Error("TeraTTS request failed");
  }
}

Remote("synthesize")(TeraTtsVoiceService.prototype.synthesize, {
  kind: "method",
  name: "synthesize",
  static: false,
  private: false,
  addInitializer(initializer) {
    remoteInitializers.push(initializer);
  },
});

Remote("acquireForeground")(TeraTtsVoiceService.prototype.acquireForeground, {
  kind: "method",
  name: "acquireForeground",
  static: false,
  private: false,
  addInitializer(initializer) {
    remoteInitializers.push(initializer);
  },
});

Remote("renewForeground")(TeraTtsVoiceService.prototype.renewForeground, {
  kind: "method",
  name: "renewForeground",
  static: false,
  private: false,
  addInitializer(initializer) {
    remoteInitializers.push(initializer);
  },
});

Remote("releaseForeground")(TeraTtsVoiceService.prototype.releaseForeground, {
  kind: "method",
  name: "releaseForeground",
  static: false,
  private: false,
  addInitializer(initializer) {
    remoteInitializers.push(initializer);
  },
});

export const inject = [];

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

export function preparationListener(service, current) {
  const candidates = new WeakMap();
  return (session, event) => {
    if (session.header?.origin === "subagent") return;
    if (event.type === "turn/start") candidates.delete(session);
    if (event.type === "assistant/message") {
      candidates.delete(session);
      const { message, turn, interrupted } = event.data;
      if (
        !interrupted &&
        message.content.some((block) => block.type === "text") &&
        !message.content.some((block) => block.type === "tool-call")
      ) {
        candidates.set(session, { turn, messageId: message.id });
      }
    }
    if (event.type !== "turn/end") return;
    const candidate = candidates.get(session);
    candidates.delete(session);
    if (event.data.reason?.kind !== "completed" || candidate?.turn !== event.data.turn) return;

    try {
      const firstChunk = messageFirstChunk(session, candidate.messageId);
      if (!firstChunk) return;
      const config = { ...current() };
      const key = audioKey(firstChunk, config, service.synthesisRevision);

      if (service.cache.get(key) || service.coordinator.isForegroundActive()) return;

      service.coordinator.scheduleBackground({
        key,
        run: async (signal) => {
          if (service.coordinator.isForegroundActive() || service.cache.get(key)) return;
          const audio = await service.synthesizeConfigured(firstChunk, signal, config, key);
          service.cache.set(key, audio);
        },
      });
    } catch {
      // Discard errors in background preparation
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
  };
  let current = () => base;
  const service = new TeraTtsVoiceService(ctx, () => current());

  installSettingsSection(ctx, SETTINGS_NAMESPACE, Config, base, {
    setSource(source) {
      current = source;
      service.cache.clear();
    },
    onChange() {
      service.cache.clear();
    },
  });

  ctx.on("session/event", preparationListener(service, () => current()));
}
