import { Buffer } from "node:buffer";
import s from "@deepseek-ai/schemastery";
import { credentialRef } from "@deepseek-ai/dsh-credentials";
import { installSettingsSection, settingsNamespace } from "@deepseek-ai/dsh-settings";
import { Remote, TypertRemoteService } from "@deepseek-ai/dsh-typert-protocol";

const SETTINGS_NAMESPACE = settingsNamespace("teratts");
const DEFAULT_TOKEN_REF = "TERATTS_TOKEN";
export const MAX_RESPONSE_BYTES = 16 * 1024 * 1024; // 16 MiB

export const Config = s.object({
  endpoint: s.string().default("http://127.0.0.1:8088"),
  timeoutMs: s.number().step(1).min(1).default(30_000),
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

  const basePath = parsed.pathname.replace(/\/+$/, "");
  parsed.pathname = `${basePath}/tts`;
  return parsed.toString();
}

function parseRetryAfter(response, errorBody) {
  let retryAfterMs;
  const retryAfterHeader = response.headers.get("retry-after");
  if (retryAfterHeader) {
    const seconds = Number.parseFloat(retryAfterHeader);
    if (!Number.isNaN(seconds) && seconds >= 0) {
      retryAfterMs = Math.round(seconds * 1000);
    } else {
      const dateMs = Date.parse(retryAfterHeader);
      if (!Number.isNaN(dateMs)) {
        retryAfterMs = Math.max(0, dateMs - Date.now());
      }
    }
  }

  if (typeof errorBody === "object" && errorBody !== null) {
    if (typeof errorBody.retry_after_ms === "number" && errorBody.retry_after_ms >= 0) {
      retryAfterMs = errorBody.retry_after_ms;
    } else if (typeof errorBody.retry_after === "number" && errorBody.retry_after >= 0) {
      retryAfterMs = Math.round(errorBody.retry_after * 1000);
    }
  }

  return retryAfterMs;
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
      if (err.message && err.message.includes("16 MiB limit")) {
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
    for (const initialize of remoteInitializers) initialize.call(this);
  }

  async synthesize(text, signal) {
    if (typeof text !== "string" || text.trim().length === 0) {
      throw new TypeError("TeraTTS text must not be empty");
    }

    const config = this.current();
    const language = config.language === "en" ? "en" : "ru";
    const endpoint = validateAndResolveEndpoint(config.endpoint);

    const timeout = AbortSignal.timeout(config.timeoutMs);
    const requestSignal = signal ? AbortSignal.any([signal, timeout]) : timeout;

    const credentials = this.ctx.get("credentials");
    const token = credentials
      ? await credentials.resolve(credentialRef(config.tokenEnv))
      : undefined;

    let response;
    try {
      response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          ...(token ? { authorization: `Bearer ${token.value}` } : {}),
        },
        body: JSON.stringify({
          text,
          voice: config.voice,
          language,
          russian_stress: config.stress === true,
          speech_front: config.speechFront !== false,
          duration_scale: 1,
        }),
        signal: requestSignal,
      });
    } catch (error) {
      console.error(`[teratts] fetch to ${endpoint} failed:`, error);
      if (error?.name === "AbortError") throw error;
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
      const error = new Error(`TeraTTS request failed with HTTP ${response.status}${retrySuffix}`);
      if (retryAfterMs !== undefined) {
        error.retryAfterMs = retryAfterMs;
        error.retry_after_ms = retryAfterMs;
      }
      error.status = response.status;
      throw error;
    }

    const audio = await readAudioResponse(response);
    return {
      audioBase64: audio.toString("base64"),
      mimeType: response.headers.get("content-type")?.split(";", 1)[0] || "audio/wav",
    };
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

export function apply(ctx, config = {}) {
  const base = {
    endpoint: config.endpoint ?? "http://127.0.0.1:8088",
    timeoutMs: config.timeoutMs ?? 30_000,
    voice: config.voice ?? "ru_f1",
    language: config.language ?? "ru",
    stress: config.stress ?? false,
    speechFront: config.speechFront ?? true,
    tokenEnv: config.tokenEnv ?? DEFAULT_TOKEN_REF,
  };
  let current = () => base;
  installSettingsSection(ctx, SETTINGS_NAMESPACE, Config, base, {
    setSource(source) {
      current = source;
    },
    onChange() {},
  });
  new TeraTtsVoiceService(ctx, () => current());
}
