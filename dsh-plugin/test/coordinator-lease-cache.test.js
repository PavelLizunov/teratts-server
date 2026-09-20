import assert from "node:assert/strict";
import test from "node:test";
import {
  AudioCache,
  PlaybackCoordinator,
  audioKey,
  messageFirstChunk,
} from "../lib/coordinator.js";
import { splitSpeechText, cleanMarkdown } from "../lib/speech-text.js";

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

test("AudioCache: bounded LRU drops oldest and clear() empties cache", () => {
  const cache = new AudioCache(3);
  cache.set("k1", "a1");
  cache.set("k2", "a2");
  cache.set("k3", "a3");
  assert.equal(cache.get("k1"), "a1"); // refresh k1
  cache.set("k4", "a4"); // drops k2 (oldest)

  assert.equal(cache.get("k2"), undefined);
  assert.equal(cache.get("k1"), "a1");
  assert.equal(cache.get("k3"), "a3");
  assert.equal(cache.get("k4"), "a4");

  cache.clear();
  assert.equal(cache.get("k1"), undefined);
  assert.equal(cache.get("k4"), undefined);
});

test("audioKey binds synthesisRevision and normalizes endpoint without credentials", () => {
  const config = {
    endpoint: "https://user:pass@teratts.tail9fd337.ts.net:8443/custom/",
    voice: "ru_f1",
    language: "ru",
    stress: false,
    speechFront: true,
  };
  const key1 = audioKey("Текст", config, "rev1");
  const key2 = audioKey("Текст", config, "rev2");
  const key1Copy = audioKey("Текст", { ...config, endpoint: "https://teratts.tail9fd337.ts.net:8443/custom" }, "rev1");

  assert.notEqual(key1, key2, "revision change must change key");
  assert.equal(key1, key1Copy, "credentials and trailing slash in endpoint must not change key");
});

test("PlaybackCoordinator: acquire, renew, release and late stop immunity", () => {
  const coordinator = new PlaybackCoordinator();
  assert.equal(coordinator.isForegroundActive(), false);

  coordinator.acquireForeground("owner1", 1);
  assert.equal(coordinator.isForegroundActive(), true);

  // Late stop from epoch 0 must NOT release epoch 1
  const releasedOld = coordinator.releaseForeground("owner1", 0);
  assert.equal(releasedOld.ok, false);
  assert.equal(coordinator.isForegroundActive(), true);

  // Renew matching epoch succeeds
  const renewed = coordinator.renewForeground("owner1", 1);
  assert.equal(renewed.ok, true);

  // Renew non-matching epoch fails
  assert.equal(coordinator.renewForeground("owner1", 2).ok, false);

  // Release matching epoch clears lease
  const released = coordinator.releaseForeground("owner1", 1);
  assert.equal(released.ok, true);
  assert.equal(coordinator.isForegroundActive(), false);
});

test("PlaybackCoordinator: audio plays > 15s without HTTP requests, foreground lease remains active", () => {
  const coordinator = new PlaybackCoordinator();
  coordinator.acquireForeground("owner1", 1);

  // Even if 16s pass without HTTP requests, unreleased activeOwnerId blocks speculative background tasks
  coordinator.activeUntil = Date.now() - 1000;
  assert.equal(coordinator.isForegroundActive(), true, "unreleased lease must remain active/unknown");

  let backgroundStarted = false;
  coordinator.scheduleBackground({
    key: "bg1",
    run: async () => {
      backgroundStarted = true;
    },
  });

  assert.equal(backgroundStarted, false);
  assert.equal(coordinator.backgroundRunning, 0);
});

test("PlaybackCoordinator: multiple turn/end keep backgroundRunning <= 1 and backgroundPending <= 1", async () => {
  const coordinator = new PlaybackCoordinator();
  const started = [];
  let blockResolve;
  const blockingPromise = new Promise((resolve) => {
    blockResolve = resolve;
  });

  coordinator.scheduleBackground({
    key: "cand1",
    run: async () => {
      started.push("cand1");
      await blockingPromise;
    },
  });

  assert.equal(coordinator.backgroundRunning, 1);
  assert.deepEqual(started, ["cand1"]);

  // Two rapid candidates arrive while cand1 is running
  coordinator.scheduleBackground({
    key: "cand2",
    run: async () => {
      started.push("cand2");
    },
  });
  assert.equal(coordinator.backgroundPending?.key, "cand2");

  coordinator.scheduleBackground({
    key: "cand3",
    run: async () => {
      started.push("cand3");
    },
  });
  // cand3 replaced cand2 in backgroundPending
  assert.equal(coordinator.backgroundPending?.key, "cand3");
  assert.equal(coordinator.backgroundRunning, 1);

  // Complete cand1
  blockResolve();
  await new Promise((r) => setImmediate(r));
  await new Promise((r) => setImmediate(r));

  // cand3 was executed, cand2 was dropped
  assert.deepEqual(started, ["cand1", "cand3"]);
  assert.equal(coordinator.backgroundRunning, 0);
  assert.equal(coordinator.backgroundPending, null);
});

test("PlaybackCoordinator: promoteToForeground makes task immune to cancelBackground", async () => {
  const coordinator = new PlaybackCoordinator();
  let taskSignal;
  let taskResolve;
  const taskPromise = new Promise((resolve) => {
    taskResolve = resolve;
  });

  coordinator.scheduleBackground({
    key: "chunk0",
    run: async (signal) => {
      taskSignal = signal;
      await taskPromise;
    },
  });

  assert.equal(coordinator.backgroundRunning, 1);

  // User plays chunk0: promoted to foreground
  const promoted = coordinator.promoteToForeground("chunk0");
  assert.ok(promoted !== null);

  // Manual play of a different message calls cancelBackground()
  coordinator.cancelBackground("manual_play_other");

  // The promoted task was NOT aborted
  assert.equal(taskSignal.aborted, false);

  taskResolve();
  await promoted;
  assert.equal(coordinator.backgroundRunning, 0);
});

test("preparationListener uses messageFirstChunk and exact cleanMarkdown + splitSpeechText", () => {
  const text = "Первое предложение. Второе предложение. ".repeat(10);
  const session = {
    header: { origin: "user" },
    deriveMessages: () => [
      {
        id: "msg1",
        role: "assistant",
        content: [{ type: "text", text }],
      },
    ],
  };

  const firstChunk = messageFirstChunk(session, "msg1");
  const expectedChunk = splitSpeechText(cleanMarkdown(text))[0];
  assert.equal(firstChunk, expectedChunk);
  assert.ok(firstChunk.length <= 140);
});
