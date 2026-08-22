import { Buffer } from "node:buffer";
import s from "@deepseek-ai/schemastery";
import { credentialRef } from "@deepseek-ai/dsh-credentials";
import { installSettingsSection, settingsNamespace } from "@deepseek-ai/dsh-settings";
import { Remote, TypertRemoteService } from "@deepseek-ai/dsh-typert-protocol";

const SETTINGS_NAMESPACE = settingsNamespace("teratts");
const DEFAULT_TOKEN_REF = "TERATTS_TOKEN";

export const Config = s.object({
  endpoint: s.string().default("http://127.0.0.1:8088"),
  timeoutMs: s.number().step(1).min(1).default(30_000),
  voice: s.string().default("ru_f1"),
  tokenEnv: s.string().role("credential-ref").default(DEFAULT_TOKEN_REF),
});

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
    const endpoint = new URL("/tts", config.endpoint).toString();
    const timeout = AbortSignal.timeout(config.timeoutMs);
    const requestSignal = signal ? AbortSignal.any([signal, timeout]) : timeout;
    const credentials = this.ctx.get("credentials");
    const token = credentials
      ? await credentials.resolve(credentialRef(config.tokenEnv))
      : undefined;

    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...(token ? { authorization: `Bearer ${token.value}` } : {}),
      },
      body: JSON.stringify({ text, voice: config.voice, duration_scale: 1 }),
      signal: requestSignal,
    });

    if (!response.ok) {
      throw new Error(`TeraTTS request failed with HTTP ${response.status}`);
    }

    const audio = Buffer.from(await response.arrayBuffer());
    if (audio.length === 0) throw new Error("TeraTTS returned empty audio");
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
