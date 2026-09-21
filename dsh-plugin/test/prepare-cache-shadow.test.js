import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  PreparedTextCache,
  prepareKey,
  PlaybackCoordinator,
} from "../lib/coordinator.js";

const hostPath = new URL("../lib/index.js", import.meta.url);
const host = await readFile(hostPath, "utf8");

const fnSource = host
  .slice(
    host.indexOf("function isLoopbackHost"),
    host.indexOf("const remoteInitializers = [];"),
  )
  .replace(/export\s+/g, "");

const helpers = {};
const factory = new Function(
  "exports",
  "URL",
  "Number",
  fnSource +
    "\nexports.validateAndResolveEndpoint = validateAndResolveEndpoint;\nexports.validateAndResolvePrepareEndpoint = validateAndResolvePrepareEndpoint;"
);
factory(helpers, URL, Number);
const { validateAndResolvePrepareEndpoint, validateAndResolveEndpoint } = helpers;

test("PreparedTextCache: stores entries, refreshes LRU and evicts oldest when exceeding maxEntries", () => {
  const cache = new PreparedTextCache({ maxEntries: 3, ttlMs: 60_000 });

  assert.equal(cache.set("k1", { text: "Text 1", preparationRevision: "r1" }), true);
  assert.equal(cache.set("k2", { text: "Text 2", preparationRevision: "r1" }), true);
  assert.equal(cache.set("k3", { text: "Text 3", preparationRevision: "r1" }), true);
  assert.equal(cache.entryCount, 3);

  // Access k1 -> refreshes LRU
  assert.equal(cache.get("k1", "r1")?.text, "Text 1");

  // Add k4 -> evicts oldest unaccessed entry (k2)
  assert.equal(cache.set("k4", { text: "Text 4", preparationRevision: "r1" }), true);
  assert.equal(cache.entryCount, 3);
  assert.equal(cache.get("k2", "r1"), undefined, "k2 should be evicted");
  assert.equal(cache.get("k1", "r1")?.text, "Text 1");
  assert.equal(cache.get("k3", "r1")?.text, "Text 3");
  assert.equal(cache.get("k4", "r1")?.text, "Text 4");
});

test("PreparedTextCache: invalidates on revision mismatch or TTL expiry", async () => {
  const cache = new PreparedTextCache({ maxEntries: 5, ttlMs: 30 });

  cache.set("k_rev", { text: "Revision text", preparationRevision: "r1" });
  // Revision mismatch deletes entry
  assert.equal(cache.get("k_rev", "r2"), undefined);
  assert.equal(cache.entryCount, 0);

  cache.set("k_ttl", { text: "TTL text", preparationRevision: "r1" });
  assert.equal(cache.get("k_ttl", "r1")?.text, "TTL text");

  // Wait 35ms for TTL expiry
  await new Promise((resolve) => setTimeout(resolve, 35));
  assert.equal(cache.get("k_ttl", "r1"), undefined);
  assert.equal(cache.entryCount, 0);
});

test("prepareKey: depends only on message identity, revision, format and language (voice/model independent)", () => {
  const key1 = prepareKey("msg_123", "1", "markdown", "ru", "v1");
  const key2 = prepareKey("msg_123", "1", "markdown", "ru", "v1");
  assert.equal(key1, key2);

  // Different message revision
  const keyRev2 = prepareKey("msg_123", "2", "markdown", "ru", "v1");
  assert.notEqual(key1, keyRev2);

  // Different language
  const keyEn = prepareKey("msg_123", "1", "markdown", "en", "v1");
  assert.notEqual(key1, keyEn);

  // Different input format
  const keyPlain = prepareKey("msg_123", "1", "plain", "ru", "v1");
  assert.notEqual(key1, keyPlain);
});

test("PlaybackCoordinator.schedulePrepareJob: deduplicates simultaneous prepare requests and shares single promise", async () => {
  const coordinator = new PlaybackCoordinator();
  let calls = 0;
  let finishTask;

  const runFn = async () => {
    calls++;
    return new Promise((resolve) => {
      finishTask = () => resolve({ text: "Prepared result", preparationRevision: "r1" });
    });
  };

  // Two consumers request preparation for the same key simultaneously
  const p1 = coordinator.schedulePrepareJob("key_dup", "consumer_bg", runFn);
  const p2 = coordinator.schedulePrepareJob("key_dup", "consumer_fg", runFn);

  assert.equal(calls, 1, "runFn must be called only once");
  assert.equal(p1, p2, "both consumers must receive the exact same promise");

  const inFlight = coordinator.getInFlightPrepare("key_dup");
  assert.ok(inFlight !== undefined);
  assert.equal(inFlight.consumers.size, 2);

  finishTask();
  const res1 = await p1;
  const res2 = await p2;

  assert.deepEqual(res1, res2);
  assert.equal(res1.text, "Prepared result");

  // In-flight entry is cleaned up after settlement
  assert.equal(coordinator.getInFlightPrepare("key_dup"), undefined);
});

test("validateAndResolvePrepareEndpoint: resolves /prepare path and preserves allowed loopback / tailnet rules", () => {
  // Loopback http
  const ep1 = validateAndResolvePrepareEndpoint("http://127.0.0.1:8088/tts");
  assert.equal(ep1, "http://127.0.0.1:8088/prepare");

  const ep2 = validateAndResolvePrepareEndpoint("http://localhost:8088");
  assert.equal(ep2, "http://localhost:8088/prepare");

  // Tailnet https
  const ep3 = validateAndResolvePrepareEndpoint("https://teratts.tail9fd337.ts.net/tts");
  assert.equal(ep3, "https://teratts.tail9fd337.ts.net/prepare");

  // Disallowed endpoints throw
  assert.throws(() => {
    validateAndResolvePrepareEndpoint("http://example.com/tts");
  }, /not allowed/);
  assert.throws(() => {
    validateAndResolvePrepareEndpoint("http://192.168.1.50:8088");
  }, /not allowed/);
});
