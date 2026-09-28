import assert from "node:assert/strict";
import test from "node:test";
import { PlaybackCoordinator } from "../lib/coordinator.js";

const flush = () => new Promise((resolve) => setImmediate(resolve));

test("lease deadline wakes queued speculation without a new event", async (t) => {
  t.mock.timers.enable({ apis: ["Date", "setTimeout"], now: 1000 });
  const coordinator = new PlaybackCoordinator();
  t.after(() => coordinator.dispose());
  coordinator.acquireForeground("tab", 1);
  let started = 0;
  coordinator.scheduleSessionCandidate("chat", {
    key: "queued", candidateGeneration: 1,
    run: async () => { started += 1; },
  });
  t.mock.timers.tick(14999);
  assert.equal(started, 0);
  t.mock.timers.tick(1);
  await flush();
  assert.equal(started, 1);
  assert.equal(coordinator.activeLeases.size, 0);
});

test("lease renewal extends deadline and stale epochs cannot replace active owners", (t) => {
  t.mock.timers.enable({ apis: ["Date", "setTimeout"], now: 1000 });
  const coordinator = new PlaybackCoordinator();
  t.after(() => coordinator.dispose());
  coordinator.acquireForeground("tab", 2);
  assert.equal(coordinator.acquireForeground("tab", 1).ok, false);
  assert.equal(coordinator.releaseForeground("tab", 1).ok, false);
  t.mock.timers.tick(10000);
  assert.equal(coordinator.renewForeground("tab", 2).ok, true);
  t.mock.timers.tick(5000);
  assert.equal(coordinator.isForegroundActive(), true);
  t.mock.timers.tick(10000);
  assert.equal(coordinator.isForegroundActive(), false);
  assert.equal(coordinator.renewForeground("tab", 2).ok, false);
});

test("remote lease registry rejects malformed identities and remains bounded", () => {
  const coordinator = new PlaybackCoordinator();
  try {
    for (const [owner, epoch] of [["", 1], ["x".repeat(257), 1], [null, 1], ["tab", NaN], ["tab", Infinity], ["tab", -1], ["tab", "1"]]) {
      assert.equal(coordinator.acquireForeground(owner, epoch).ok, false);
    }
    for (let i = 0; i < 32; i++) assert.equal(coordinator.acquireForeground(`tab-${i}`, 1).ok, true);
    assert.equal(coordinator.acquireForeground("overflow", 1).ok, false);
    assert.equal(coordinator.acquireForeground("tab-0", 2).ok, true);
  } finally { coordinator.dispose(); }
});

test("dispose clears lease wakeup and never dispatches pending work", async (t) => {
  t.mock.timers.enable({ apis: ["Date", "setTimeout"], now: 1000 });
  const coordinator = new PlaybackCoordinator();
  coordinator.acquireForeground("tab", 1);
  let started = 0;
  coordinator.scheduleSessionCandidate("chat", { key: "pending", run: async () => { started++; } });
  coordinator.dispose();
  t.mock.timers.tick(20000);
  await flush();
  assert.equal(started, 0);
  assert.equal(coordinator.leaseTimer, null);
  assert.equal(coordinator.acquireForeground("tab", 2).ok, false);
});

test("evicted prepare waiters leave no rejected promise in the deduplication registry", async () => {
  const coordinator = new PlaybackCoordinator();
  let finish;
  const active = coordinator.schedulePrepareJob("active", "c", () => new Promise((resolve) => { finish = resolve; }));
  const waiters = [];
  for (let i = 0; i < 9; i++) {
    waiters.push(coordinator.schedulePrepareJob(`queued-${i}`, "c", async () => i).catch((error) => error));
  }
  assert.match((await waiters[0]).message, /capacity/);
  assert.equal(coordinator.inFlightPrepares.has("queued-0"), false);
  assert.equal(coordinator.prepareRunning, 1, "eviction must not release the running job's slot");
  finish("done");
  await active;
  await Promise.all(waiters);
  assert.equal(coordinator.inFlightPrepares.size, 0);
  assert.equal(await coordinator.schedulePrepareJob("queued-0", "c", async () => "retry"), "retry");
});

test("dispose aborts active preparation and rejects waiters without running them", async () => {
  const coordinator = new PlaybackCoordinator();
  let started = 0;
  const active = coordinator.schedulePrepareJob("active", "c", (signal) => new Promise((resolve, reject) => {
    signal.addEventListener("abort", () => reject(signal.reason), { once: true });
  }));
  const waiting = coordinator.schedulePrepareJob("waiting", "c", async () => { started++; });
  const activeCheck = assert.rejects(active, { name: "AbortError" });
  const waitingCheck = assert.rejects(waiting, /disposed/);
  coordinator.dispose();
  await Promise.all([activeCheck, waitingCheck]);
  assert.equal(started, 0);
  assert.equal(coordinator.prepareRunning, 0);
  assert.equal(coordinator.prepareQueue.size, 0);
  assert.equal(coordinator.inFlightPrepares.size, 0);
  await assert.rejects(coordinator.schedulePrepareJob("late", "c", async () => {}), /disposed/);
});

test("synchronous prepare failure releases its slot and in-flight registry", async () => {
  const coordinator = new PlaybackCoordinator();
  await assert.rejects(coordinator.schedulePrepareJob("bad", "consumer", () => {
    throw new Error("expected prepare failure");
  }), /expected prepare failure/);
  assert.equal(coordinator.prepareRunning, 0);
  assert.equal(coordinator.inFlightPrepares.size, 0);
  assert.equal(await coordinator.schedulePrepareJob("good", "consumer", async () => "prepared"), "prepared");
});

test("promotion rejects speculative audio admitted before settings reset", async () => {
  const coordinator = new PlaybackCoordinator();
  let finish;
  coordinator.scheduleSessionCandidate("chat", {
    key: "same-key", cacheGeneration: 1,
    run: () => new Promise((resolve) => { finish = resolve; }),
  });
  assert.equal(coordinator.promoteJob("same-key", "new-settings", 2), null);
  const promoted = coordinator.promoteJob("same-key", "same-settings", 1);
  assert.ok(promoted instanceof Promise);
  finish("audio");
  assert.equal(await promoted, "audio");
});

test("expired foreground leases do not permanently disable speculation", () => {
  const coordinator = new PlaybackCoordinator();
  coordinator.acquireForeground("closed-tab", 1);
  coordinator.activeLeases.get("closed-tab").until = Date.now() - 1;
  assert.equal(coordinator.isForegroundActive(), false);
});

test("a rejected speculative candidate is attempted once, not recursively retried", async () => {
  const coordinator = new PlaybackCoordinator();
  let attempts = 0;
  coordinator.scheduleSessionCandidate("chat", {
    candidateGeneration: 1,
    key: "rejected",
    run: async () => {
      attempts += 1;
      // Bound the defective baseline so the regression itself cannot spin forever.
      if (attempts === 2) coordinator.acquireForeground("test-stop", 1);
      throw new Error("HTTP 400: unsupported input");
    },
  });
  await flush();
  assert.equal(attempts, 1);
  assert.equal(coordinator.sessionCandidates.size, 0);
  assert.equal(coordinator.backgroundRunning, 0);
});

test("a synchronous speculative throw leaves no stale in-flight job", async () => {
  const coordinator = new PlaybackCoordinator();
  let attempts = 0;
  coordinator.scheduleSessionCandidate("chat", {
    candidateGeneration: 1,
    key: "sync-error",
    run: () => {
      attempts += 1;
      coordinator.acquireForeground("test-stop", 1);
      throw new Error("synchronous failure");
    },
  });
  await flush();
  assert.equal(attempts, 1);
  assert.equal(coordinator.inFlightJobs.size, 0);
  assert.equal(coordinator.sessionCandidates.size, 0);
});
