import assert from "node:assert/strict";
import test from "node:test";
import { PlaybackCoordinator } from "../lib/coordinator.js";

const response = (revision) => ({ ok: true, json: async () => ({ synthesis_revision: revision }) });

test("metadata cache is scoped to the endpoint", async (t) => {
  const c = new PlaybackCoordinator();
  let calls = 0;
  t.mock.method(globalThis, "fetch", async (url) => { calls++; return response(String(url).includes("8088") ? "a" : "b"); });
  assert.equal(await c.getOrFetchSynthesisRevision("http://127.0.0.1:8088/tts"), "a");
  assert.equal(await c.getOrFetchSynthesisRevision("http://127.0.0.1:8089/tts"), "b");
  assert.equal(calls, 2);
});

test("late old endpoint response cannot overwrite newer metadata", async (t) => {
  const c = new PlaybackCoordinator();
  let finishA;
  t.mock.method(globalThis, "fetch", (url) => String(url).includes("8088")
    ? new Promise((resolve) => { finishA = resolve; }) : Promise.resolve(response("b")));
  const a = c.getOrFetchSynthesisRevision("http://127.0.0.1:8088/tts");
  // Wait for dispatch without depending on implementation's microtask scheduling.
  await new Promise((resolve) => setImmediate(resolve));
  const b = c.getOrFetchSynthesisRevision("http://127.0.0.1:8089/tts");
  finishA(response("a"));
  assert.equal(await b, "b");
  assert.equal(await a, "a");
  assert.equal(await c.getOrFetchSynthesisRevision("http://127.0.0.1:8089/tts"), "b");
});

test("metadata requests prohibit redirects and use URL path semantics", async (t) => {
  const c = new PlaybackCoordinator();
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(String(url), "http://127.0.0.1:8088/api/health?mode=test");
    assert.equal(options.redirect, "error");
    return response("r1");
  });
  assert.equal(await c.getOrFetchSynthesisRevision("http://127.0.0.1:8088/api/tts?mode=test"), "r1");
});
