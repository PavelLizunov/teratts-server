import { Buffer } from "node:buffer";
import s from "@deepseek-ai/schemastery";
import { credentialRef } from "@deepseek-ai/dsh-credentials";
import { installSettingsSection, settingsNamespace } from "@deepseek-ai/dsh-settings";

const SETTINGS_NAMESPACE = settingsNamespace("teratts");
const DEFAULT_TOKEN_REF = "TERATTS_TOKEN";

export const Config = s.object({
  endpoint: s.string().default("http://127.0.0.1:8088"),
  timeoutMs: s.number().step(1).min(1).default(30_000),
  voice: s.string().default("ru_f1"),
  tokenEnv: s.string().role("credential-ref").default(DEFAULT_TOKEN_REF),
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

  ctx.handle("synthesize", async (args) => {
    const text = typeof args === "object" && args !== null ? args.text : args;
    if (typeof text !== "string" || text.trim().length === 0) {
      throw new TypeError("TeraTTS text must not be empty");
    }

    const cfg = current();
    const endpoint = new URL("/tts", cfg.endpoint).toString();
    const timeout = AbortSignal.timeout(cfg.timeoutMs);
    const credentials = ctx.get("credentials");
    const token = credentials
      ? await credentials.resolve(credentialRef(cfg.tokenEnv))
      : undefined;

    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...(token ? { authorization: `Bearer ${token.value}` } : {}),
      },
      body: JSON.stringify({ text, voice: cfg.voice, duration_scale: 1 }),
      signal: timeout,
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
  });
}
