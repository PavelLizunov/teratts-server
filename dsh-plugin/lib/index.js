import { Buffer } from "node:buffer";
import s from "@deepseek-ai/schemastery";
import { credentialRef } from "@deepseek-ai/dsh-credentials";
import { Remote, TypertRemoteService } from "@deepseek-ai/dsh-typert-protocol";
import {
  ByteBoundedAudioCache,
  PlaybackCoordinator,
  PreparedTextCache,
  audioKey,
  prepareKey,
  messageFirstChunk,
  messageRawText,
  normalizeEndpointWithoutAuth,
} from "./coordinator.js";

const SETTINGS_NAMESPACE = "teratts";
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

const remoteInitializers = [];

export class TeraTtsVoiceService extends TypertRemoteService {
  constructor(ctx, current) {
    super(ctx, "terattsVoice");
    this.current = current;
    this.cache = new ByteBoundedAudioCache();
    this.preparedTextCache = new PreparedTextCache();
    this.coordinator = new PlaybackCoordinator();
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

  async synthesize(text, signal) {
    if (typeof text !== "string" || text.trim().length === 0) {
      throw new TypeError("TeraTTS text must not be empty");
    }

    const config = this.current();

    // Validate/refresh revision with 30s bounded staleness
    const freshRevision = await this.coordinator.getOrFetchSynthesisRevision(config.endpoint);
    if (freshRevision && freshRevision !== this.synthesisRevision) {
      this.synthesisRevision = freshRevision;
      this.cache.invalidateRevision(freshRevision);
    }

    const key = audioKey(text, config, this.synthesisRevision);

    // 1. Check if matching job is currently in flight -> promote it to foreground
    const consumerId = `req_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    const promotedPromise = this.coordinator.promoteJob(key, consumerId);
    if (promotedPromise) {
      try {
        const audioResult = await promotedPromise;
        if (audioResult && audioResult.audioBuffer) {
          return {
            audioBase64: audioResult.audioBuffer.toString("base64"),
            mimeType: audioResult.mimeType || "audio/wav",
          };
        }
      } catch {
        // If background job threw, fall through to direct fetch
      }
    }

    // 2. Check LRU cache (returns Buffer if hit and revision matches)
    const cached = this.cache.get(key, this.synthesisRevision);
    if (cached && cached.audioBuffer) {
      return {
        audioBase64: cached.audioBuffer.toString("base64"),
        mimeType: cached.mimeType || "audio/wav",
      };
    }

    // 3. Perform direct configured fetch
    const currentGeneration = this.cache.generation;
    const audioResult = await this.synthesizeConfigured(text, signal, config, key);

    // Update revision if server response header advertised newer revision
    if (audioResult.synthesisRevision && audioResult.synthesisRevision !== this.synthesisRevision) {
      this.synthesisRevision = audioResult.synthesisRevision;
      this.cache.invalidateRevision(audioResult.synthesisRevision);
    }

    // Cache the raw binary buffer (max 4 MiB)
    this.cache.set(key, audioResult, currentGeneration);

    return {
      audioBase64: audioResult.audioBuffer.toString("base64"),
      mimeType: audioResult.mimeType,
    };
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
      input_format: "plain",
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

Remote("synthesize")(TeraTtsVoiceService.prototype.synthesize, {
  kind: "method",
  name: "synthesize",
  static: false,
  private: false,
  addInitializer(initializer) {
    remoteInitializers.push(initializer);
  },
});

export const inject = [];

export function preparationListener(service, current) {
  const sessionGenerations = new Map(); // sessionId -> number
  const candidateTurns = new WeakMap();

  return (session, event) => {
    if (session.header?.origin === "subagent") return;
    const sessionId = session.id;
    if (!sessionId) return;

    if (event.type === "session/remove") {
      service.coordinator.removeSession(sessionId);
      sessionGenerations.delete(sessionId);
      candidateTurns.delete(session);
      return;
    }

    if (event.type === "turn/start") {
      candidateTurns.delete(session);
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

      const firstChunk = oldChunk0;
      const key = audioKey(firstChunk, config, service.synthesisRevision);

      // If already cached or lease is active, skip scheduling
      if (service.cache.get(key, service.synthesisRevision) || service.coordinator.isForegroundActive()) {
        return;
      }

      const nextGen = (sessionGenerations.get(sessionId) ?? 0) + 1;
      sessionGenerations.set(sessionId, nextGen);

      service.coordinator.scheduleSessionCandidate(sessionId, {
        sessionId,
        messageId: candidateData.messageId,
        candidateGeneration: nextGen,
        key,
        text: firstChunk,
        config,
        run: async (signal) => {
          if (service.coordinator.isForegroundActive() || service.cache.get(key, service.synthesisRevision)) {
            return null;
          }
          const cacheGen = service.cache.generation;
          const result = await service.synthesizeConfigured(firstChunk, signal, config, key);
          service.cache.set(key, result, cacheGen);
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
  };
  let current = () => base;
  const service = new TeraTtsVoiceService(ctx, () => current());

  const installSection = (settingsService) => {
    settingsService.installSection(ctx, SETTINGS_NAMESPACE, Config, base, {
      setSource(source) {
        current = source;
        service.cache.clear();
        service.preparedTextCache.clear();
      },
      onChange() {
        service.cache.clear();
        service.preparedTextCache.clear();
      },
    });
  };

  if (typeof ctx.inject === "function") {
    ctx.inject(["settings"], (settingsCtx) => {
      if (settingsCtx.settings && typeof settingsCtx.settings.installSection === "function") {
        installSection(settingsCtx.settings);
      }
    });
  } else {
    const settingsService = ctx.get ? ctx.get("settings") : ctx.settings;
    if (settingsService && typeof settingsService.installSection === "function") {
      installSection(settingsService);
    }
  }

  ctx.on("session/event", preparationListener(service, () => current()));
}
