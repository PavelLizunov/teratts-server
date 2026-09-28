import assert from "node:assert/strict";
import test from "node:test";
import { isolatedService } from "./helpers/runtime.js";

for (const status of [502, 504]) {
  test(`HTTP ${status} does not resubmit synthesis with unknown backend completion`, async (t) => {
    const { service, config } = await isolatedService(t, { maxRetries: 1 });
    let calls = 0;
    t.mock.method(console, "error", () => {});
    t.mock.method(globalThis, "fetch", async () => {
      calls++;
      return new Response(calls === 1 ? '{"code":"deadline_exceeded"}' : "audio", { status: calls === 1 ? status : 200 });
    });
    await assert.rejects(service.synthesizeConfigured("hello", undefined, config), new RegExp(`HTTP ${status}`));
    assert.equal(calls, 1);
  });
}

for (const status of [429, 503]) {
  test(`explicit admission rejection ${status} can retry once`, async (t) => {
    const { service, config } = await isolatedService(t, { maxRetries: 1 });
    let calls = 0;
    t.mock.method(Math, "random", () => 0);
    t.mock.method(console, "error", () => {});
    t.mock.method(globalThis, "fetch", async () => {
      calls++;
      return calls === 1 ? new Response('{"code":"queue_timeout"}', { status }) : new Response("audio");
    });
    const result = await service.synthesizeConfigured("hello", undefined, config);
    assert.equal(result.audioBuffer.toString(), "audio");
    assert.equal(calls, 2);
  });
}

test("unclassified 503 is not retried and oversized error body is cancelled without logging content", async (t) => {
  const { service, config } = await isolatedService(t, { maxRetries: 1 });
  let calls = 0;
  let cancelled = false;
  const logs = [];
  t.mock.method(console, "error", (...args) => logs.push(args));
  t.mock.method(globalThis, "fetch", async () => {
    calls++;
    return new Response(new ReadableStream({
      start(controller) { controller.enqueue(new TextEncoder().encode("PRIVATE_TEXT".repeat(500))); },
      cancel() { cancelled = true; },
    }), { status: 503 });
  });
  await assert.rejects(service.synthesizeConfigured("hello", undefined, config), /HTTP 503/);
  assert.equal(calls, 1);
  assert.equal(cancelled, true);
  assert.doesNotMatch(JSON.stringify(logs), /PRIVATE_TEXT/);
});

test("network reset is not retried and preserves unknown-outcome classification", async (t) => {
  const { service, config } = await isolatedService(t, { maxRetries: 1 });
  let calls = 0;
  t.mock.method(console, "error", () => {});
  t.mock.method(globalThis, "fetch", async () => {
    calls++;
    if (calls === 1) throw new TypeError("fetch failed", { cause: { code: "ECONNRESET" } });
    return new Response("audio");
  });
  await assert.rejects(service.synthesizeConfigured("hello", undefined, config), (error) => error.backendOutcomeUnknown === true);
  assert.equal(calls, 1);
});
