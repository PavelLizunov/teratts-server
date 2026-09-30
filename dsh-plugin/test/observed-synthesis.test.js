import assert from "node:assert/strict";
import test from "node:test";
import { TeraTtsVoiceService } from "../lib/index.js";

test("observed synthesis propagates explicit IDs and preserves cached audio", async () => {
  const records = [];
  let releaseCount = 0;
  const service = {
    coordinator: { holdForegroundRequest: () => () => releaseCount++ },
    recordTelemetry: async (data) => records.push(data),
    telemetry: { record: async (data, files) => records.push({ ...data, files }) },
    synthesizeForeground: async (text, signal, context) => {
      assert.equal(text, "Текст озвучки");
      assert.equal(context.sessionId, "session");
      assert.equal(context.messageId, "message");
      assert.equal(typeof context.requestId, "string");
      return { audioBase64: Buffer.from("exact-wav").toString("base64"), telemetryCacheHit: true };
    },
  };
  const result = await TeraTtsVoiceService.prototype.synthesizeObserved.call(service,
    "Текст озвучки", { sessionId: "session", messageId: "message", originalAssistantText: "**Оригинал**" });
  assert.equal(Buffer.from(result.audioBase64, "base64").toString(), "exact-wav");
  assert.equal(releaseCount, 1);
  assert.equal(records[0].originalAssistantText, "**Оригинал**");
  assert.equal(records[1].cacheHit, true);
  assert.equal(records[1].files["synthesized.wav"].toString(), "exact-wav");
});

test("observed synthesis records failure and releases foreground lease", async () => {
  let released = false;
  const records = [];
  const service = {
    coordinator: { holdForegroundRequest: () => () => { released = true; } },
    recordTelemetry: async (data) => records.push(data),
    synthesizeForeground: async () => { throw Error("exact error"); },
  };
  await assert.rejects(() => TeraTtsVoiceService.prototype.synthesizeObserved.call(service, "text", {}), /exact error/);
  assert.equal(released, true);
  assert.equal(records[1].event, "synthesis_failed");
  assert.equal(records[1].error, "exact error");
});
