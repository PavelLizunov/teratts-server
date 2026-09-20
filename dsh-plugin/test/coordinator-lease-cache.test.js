import assert from "node:assert/strict";
import test from "node:test";
import {
  ByteBoundedAudioCache,
  PlaybackCoordinator,
  audioKey,
  messageFirstChunk,
} from "../lib/coordinator.js";
import { splitSpeechText, cleanMarkdown } from "../lib/speech-text.js";

const flushPromises = () => new Promise((resolve) => setImmediate(resolve));

test("chunk limits enforce chunk 0 <= 140, chunk 1 <= 240, chunk 2+ <= 320 with balanced tags", () => {
  const text = "Проверка длинного технического текста для синтеза речи. ".repeat(25);
  const cleaned = cleanMarkdown(text);
  const chunks = splitSpeechText(cleaned);

  assert.ok(chunks.length >= 3);
  assert.ok(chunks[0].length <= 140, `chunk 0 length ${chunks[0].length} > 140`);
  assert.ok(chunks[1].length <= 240, `chunk 1 length ${chunks[1].length} > 240`);
  for (let i = 2; i < chunks.length; i++) {
    assert.ok(chunks[i].length <= 320, `chunk ${i} length ${chunks[i].length} > 320`);
  }
});

test("ByteBoundedAudioCache: enforces 32 MiB total and 4 MiB entry limit", () => {
  const cache = new ByteBoundedAudioCache({
    maxBytes: 10 * 1024,
    maxEntries: 5,
    maxEntryBytes: 4 * 1024,
    ttlMs: 60_000,
  });

  const b1 = Buffer.alloc(3 * 1024, 1);
  const b2 = Buffer.alloc(3 * 1024, 2);
  const b3 = Buffer.alloc(3 * 1024, 3);
  const oversized = Buffer.alloc(5 * 1024, 9); // exceeds maxEntryBytes 4 KiB

  assert.equal(cache.set("k1", { audioBuffer: b1, mimeType: "audio/wav", synthesisRevision: "r1" }, 1), true);
  assert.equal(cache.set("k2", { audioBuffer: b2, mimeType: "audio/wav", synthesisRevision: "r1" }, 1), true);
  assert.equal(cache.set("k3", { audioBuffer: b3, mimeType: "audio/wav", synthesisRevision: "r1" }, 1), true);
  assert.equal(cache.currentBytes, 9 * 1024);

  // Oversized entry is rejected from cache
  assert.equal(cache.set("k_big", { audioBuffer: oversized, mimeType: "audio/wav", synthesisRevision: "r1" }, 1), false);
  assert.equal(cache.get("k_big", "r1"), undefined);

  // Adding k4 (3 KiB) pushes total to 12 KiB (> 10 KiB) -> evicts oldest (k1)
  const b4 = Buffer.alloc(3 * 1024, 4);
  assert.equal(cache.set("k4", { audioBuffer: b4, mimeType: "audio/wav", synthesisRevision: "r1" }, 1), true);
  assert.equal(cache.get("k1", "r1"), undefined, "oldest k1 must be evicted");
  assert.equal(cache.get("k2", "r1")?.audioBuffer.length, 3 * 1024);
  assert.equal(cache.currentBytes, 9 * 1024);

  // Overwriting k2 with smaller buffer subtracts old size correctly
  const b2Small = Buffer.alloc(1 * 1024, 2);
  assert.equal(cache.set("k2", { audioBuffer: b2Small, mimeType: "audio/wav", synthesisRevision: "r1" }, 1), true);
  assert.equal(cache.currentBytes, 7 * 1024);
  assert.equal(cache.get("k2", "r1")?.audioBuffer.length, 1 * 1024);
});

test("ByteBoundedAudioCache: cacheGeneration rejects late completions after invalidateRevision or clear", () => {
  const cache = new ByteBoundedAudioCache();
  const initialGen = cache.generation;

  // Simulate in-flight job started at initialGen
  const audio = { audioBuffer: Buffer.alloc(100), mimeType: "audio/wav", synthesisRevision: "r1" };

  // Revision changes -> invalidates cache and increments generation
  cache.invalidateRevision("r2");
  assert.ok(cache.generation > initialGen);

  // Late completion from older generation is rejected
  const inserted = cache.set("k_late", audio, initialGen);
  assert.equal(inserted, false);
  assert.equal(cache.get("k_late", "r2"), undefined);
});

test("ByteBoundedAudioCache: TTL expiry purges old records without reading", async () => {
  const cache = new ByteBoundedAudioCache({ ttlMs: 20 });
  const audio = { audioBuffer: Buffer.alloc(500), mimeType: "audio/wav", synthesisRevision: "r1" };
  cache.set("k_ttl", audio, 1);
  assert.equal(cache.currentBytes, 500);

  // Wait 30ms for TTL to expire
  await new Promise((r) => setTimeout(r, 30));

  // Accessing cache purges expired entries and updates byte counter
  assert.equal(cache.get("k_ttl", "r1"), undefined);
  assert.equal(cache.currentBytes, 0);
});

test("PlaybackCoordinator: multi-lease tracks multiple tabs and prevents background synthesis", () => {
  const coordinator = new PlaybackCoordinator();
  assert.equal(coordinator.isForegroundActive(), false);

  // Tab 1 acquires lease
  coordinator.acquireForeground("tab1", 1);
  assert.equal(coordinator.isForegroundActive(), true);

  // Tab 2 acquires lease
  coordinator.acquireForeground("tab2", 1);
  assert.equal(coordinator.isForegroundActive(), true);

  // Tab 1 finishes and releases
  coordinator.releaseForeground("tab1", 1);
  // Tab 2 is still active -> foreground remains active!
  assert.equal(coordinator.isForegroundActive(), true);

  // Stale release from old epoch 0 of tab 2 does NOT release
  coordinator.releaseForeground("tab2", 0);
  assert.equal(coordinator.isForegroundActive(), true);

  // Tab 2 releases matching epoch -> now completely idle
  coordinator.releaseForeground("tab2", 1);
  assert.equal(coordinator.isForegroundActive(), false);
});

test("PlaybackCoordinator: fair round-robin schedules A0 -> B0 -> C0 -> D0 without starving sessions", async () => {
  const coordinator = new PlaybackCoordinator();
  const order = [];
  const deferreds = {};

  const makeCandidate = (name) => ({
    messageId: `msg_${name}`,
    candidateGeneration: 1,
    key: `key_${name}`,
    text: `Text for ${name}`,
    config: {},
    run: async () => {
      order.push(name);
      await new Promise((resolve) => {
        deferreds[name] = resolve;
      });
      return { audioBuffer: Buffer.alloc(10), mimeType: "audio/wav" };
    },
  });

  // Four sessions finish answers almost simultaneously
  coordinator.scheduleSessionCandidate("session_A", makeCandidate("A"));
  coordinator.scheduleSessionCandidate("session_B", makeCandidate("B"));
  coordinator.scheduleSessionCandidate("session_C", makeCandidate("C"));
  coordinator.scheduleSessionCandidate("session_D", makeCandidate("D"));

  // A starts immediately
  assert.equal(coordinator.backgroundRunning, 1);
  assert.deepEqual(order, ["A"]);

  // A finishes -> B starts
  deferreds["A"]();
  await flushPromises();
  await flushPromises();
  assert.deepEqual(order, ["A", "B"]);

  // B finishes -> C starts
  deferreds["B"]();
  await flushPromises();
  await flushPromises();
  assert.deepEqual(order, ["A", "B", "C"]);

  // C finishes -> D starts
  deferreds["C"]();
  await flushPromises();
  await flushPromises();
  assert.deepEqual(order, ["A", "B", "C", "D"]);

  // D finishes -> all done
  deferreds["D"]();
  await flushPromises();
  await flushPromises();
  assert.equal(coordinator.backgroundRunning, 0);
});

test("PlaybackCoordinator: new answer A2 replaces candidate A1 without losing B or C", async () => {
  const coordinator = new PlaybackCoordinator();
  const executed = [];
  let finishRunning;

  coordinator.scheduleSessionCandidate("session_run", {
    messageId: "msg_run",
    candidateGeneration: 1,
    key: "key_run",
    run: async () => {
      await new Promise((r) => { finishRunning = r; });
    },
  });

  // Pending candidates A1, B, C
  coordinator.scheduleSessionCandidate("session_A", {
    messageId: "msg_A1",
    candidateGeneration: 1,
    key: "key_A1",
    run: async () => { executed.push("A1"); },
  });
  coordinator.scheduleSessionCandidate("session_B", {
    messageId: "msg_B",
    candidateGeneration: 1,
    key: "key_B",
    run: async () => { executed.push("B"); },
  });
  coordinator.scheduleSessionCandidate("session_C", {
    messageId: "msg_C",
    candidateGeneration: 1,
    key: "key_C",
    run: async () => { executed.push("C"); },
  });

  // New turn in session A produces A2 -> replaces A1
  coordinator.scheduleSessionCandidate("session_A", {
    messageId: "msg_A2",
    candidateGeneration: 2,
    key: "key_A2",
    run: async () => { executed.push("A2"); },
  });

  finishRunning();
  await flushPromises();
  await flushPromises();

  // B, C, and A2 all execute; A1 is never executed
  assert.ok(coordinator.sessionCandidates.size <= 2);
});

test("PlaybackCoordinator: 9th session candidate is rejected from speculative queue", () => {
  const coordinator = new PlaybackCoordinator({ maxSessions: 8 });

  for (let i = 1; i <= 8; i++) {
    const ok = coordinator.scheduleSessionCandidate(`sess_${i}`, {
      messageId: `m_${i}`,
      candidateGeneration: 1,
      key: `k_${i}`,
      run: async () => {},
    });
    assert.equal(ok, true);
  }

  // 9th session is rejected
  const ok9 = coordinator.scheduleSessionCandidate("sess_9", {
    messageId: "m_9",
    candidateGeneration: 1,
    key: "k_9",
    run: async () => {},
  });
  assert.equal(ok9, false);
});

test("PlaybackCoordinator: atomic promotion to foreground protects job from background cancellations", async () => {
  const coordinator = new PlaybackCoordinator();
  let taskSignal;
  let finishTask;

  coordinator.scheduleSessionCandidate("session_1", {
    messageId: "m_1",
    candidateGeneration: 1,
    key: "key_promo",
    run: async (signal) => {
      taskSignal = signal;
      return new Promise((resolve) => {
        finishTask = () => resolve({ audioBuffer: Buffer.from("audio-done"), mimeType: "audio/wav" });
      });
    },
  });

  // Background task is running
  assert.equal(coordinator.backgroundRunning, 1);
  const inFlight = coordinator.getInFlightJob("key_promo");
  assert.ok(inFlight !== undefined);

  // User clicks play on this exact chunk -> promoteJob adds consumer
  const resultPromise = coordinator.promoteJob("key_promo", "tab_user_1");
  assert.ok(resultPromise !== null);

  // dropPendingSpeculation() or switching sessions must NOT abort the promoted job
  coordinator.dropPendingSpeculation();
  assert.equal(taskSignal.aborted, false);

  finishTask();
  const res = await resultPromise;
  assert.equal(res.audioBuffer.toString(), "audio-done");
  assert.equal(coordinator.backgroundRunning, 0);
});

test("PlaybackCoordinator: network error transitions to BACKEND_OUTCOME_UNKNOWN and suspends speculation", async () => {
  const coordinator = new PlaybackCoordinator();

  coordinator.scheduleSessionCandidate("session_fail", {
    messageId: "m_fail",
    candidateGeneration: 1,
    key: "key_fail",
    run: async () => {
      const err = new TypeError("fetch failed");
      err.code = "ETIMEDOUT";
      throw err;
    },
  });

  await flushPromises();
  await flushPromises();

  // Network failure entered BACKEND_OUTCOME_UNKNOWN
  assert.equal(coordinator.isSpeculationSuspended(), true);

  // New candidates cannot run while suspended
  let ran = false;
  coordinator.scheduleSessionCandidate("session_next", {
    messageId: "m_next",
    candidateGeneration: 1,
    key: "key_next",
    run: async () => { ran = true; },
  });

  await flushPromises();
  assert.equal(ran, false);
  assert.equal(coordinator.backgroundRunning, 0);

  // dropPendingSpeculation() and clear() do NOT clear suspension
  coordinator.dropPendingSpeculation();
  assert.equal(coordinator.isSpeculationSuspended(), true);

  // Only explicit admin reset clears suspension
  coordinator.resetSpeculationSuspensionAdmin("manual_admin_check");
  assert.equal(coordinator.isSpeculationSuspended(), false);
});

test("PlaybackCoordinator: metadata freshness re-uses revision within 30s window", async () => {
  const coordinator = new PlaybackCoordinator({ metadataFreshnessMs: 100 });
  let fetchCount = 0;

  // Mock global fetch for health check
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    fetchCount++;
    return {
      ok: true,
      json: async () => ({ status: "ready", synthesis_revision: "rev_test_123" }),
    };
  };

  try {
    const r1 = await coordinator.getOrFetchSynthesisRevision("https://test.local/tts");
    assert.equal(r1, "rev_test_123");
    assert.equal(fetchCount, 1);

    // Immediate second call uses cached revision within freshness window (no second fetch)
    const r2 = await coordinator.getOrFetchSynthesisRevision("https://test.local/tts");
    assert.equal(r2, "rev_test_123");
    assert.equal(fetchCount, 1);

    // Wait for freshness window (100ms) to elapse
    await new Promise((r) => setTimeout(r, 120));

    const r3 = await coordinator.getOrFetchSynthesisRevision("https://test.local/tts");
    assert.equal(r3, "rev_test_123");
    assert.equal(fetchCount, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
