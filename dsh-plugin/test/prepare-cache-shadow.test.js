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

test("prepareKey: binds to message id, raw text content hash, endpoint, and revision", () => {
  const key1 = prepareKey("msg_1", "Hello world", "markdown", "ru", "http://127.0.0.1:8088", "r1");
  const key2 = prepareKey("msg_1", "Hello world", "markdown", "ru", "http://127.0.0.1:8088", "r1");
  assert.equal(key1, key2);

  // Different text content produces different key even with same messageId
  const keyEdited = prepareKey("msg_1", "Hello edited world", "markdown", "ru", "http://127.0.0.1:8088", "r1");
  assert.notEqual(key1, keyEdited);

  // Different endpoint produces different key
  const keyTailnet = prepareKey("msg_1", "Hello world", "markdown", "ru", "https://teratts.tail9fd337.ts.net", "r1");
  assert.notEqual(key1, keyTailnet);

  // Different revision produces different key
  const keyRev2 = prepareKey("msg_1", "Hello world", "markdown", "ru", "http://127.0.0.1:8088", "r2");
  assert.notEqual(key1, keyRev2);
});

test("PlaybackCoordinator.schedulePrepareJob: enforces concurrency limit of 1 and bounded queue", async () => {
  const coordinator = new PlaybackCoordinator();
  const running = [];
  const finishes = [];

  const makeJob = (id) => async () => {
    running.push(id);
    return new Promise((resolve) => {
      finishes.push(() => resolve({ text: `Done ${id}`, preparationRevision: "r1" }));
    });
  };

  const p1 = coordinator.schedulePrepareJob("k1", "c1", makeJob("job1"));
  const p2 = coordinator.schedulePrepareJob("k2", "c2", makeJob("job2"));

  // Only job1 starts immediately; job2 waits in queue
  assert.deepEqual(running, ["job1"]);
  assert.equal(coordinator.prepareRunning, 1);
  assert.equal(coordinator.prepareQueue.size, 1);

  // Finish job1 -> job2 begins
  finishes[0]();
  await p1;
  assert.deepEqual(running, ["job1", "job2"]);

  finishes[1]();
  await p2;
  assert.equal(coordinator.prepareRunning, 0);
  assert.equal(coordinator.prepareStats.requests, 2);
});

test("Shadow Mode invariant: failing or slow /prepare does NOT suspend speculation or abort audio job", async () => {
  const coordinator = new PlaybackCoordinator();

  // 1. Slow prepare task blocked on promise
  let finishSlowPrepare;
  const pPrepare = coordinator.schedulePrepareJob("prep_slow", "c1", async () => {
    return new Promise((resolve) => {
      finishSlowPrepare = () => resolve({ text: "Slow prepared text", preparationRevision: "r1" });
    });
  });

  // 2. Audio candidate runs and completes without waiting for prepare
  let audioRan = false;
  coordinator.scheduleSessionCandidate("session_1", {
    sessionId: "session_1",
    messageId: "msg_1",
    candidateGeneration: 1,
    key: "audio_k1",
    run: async () => {
      audioRan = true;
      return { audioBuffer: Buffer.from("wav"), mimeType: "audio/wav" };
    },
  });

  // Audio ran immediately even though prepare is still pending
  assert.equal(audioRan, true);
  assert.equal(coordinator.isSpeculationSuspended(), false);

  finishSlowPrepare();
  await pPrepare;

  // 3. Failing prepare (500, network drop)
  try {
    await coordinator.schedulePrepareJob("prep_fail", "c1", async () => {
      throw new Error("HTTP 500 error from prepare");
    });
  } catch {
    // Error caught
  }

  // Speculation is NOT suspended by prepare failures
  assert.equal(coordinator.isSpeculationSuspended(), false);
  assert.equal(coordinator.prepareStats.errors, 1);
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
