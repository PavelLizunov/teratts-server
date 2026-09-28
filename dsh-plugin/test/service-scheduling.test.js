import assert from "node:assert/strict";
import test from "node:test";
import { isolatedService } from "./helpers/runtime.js";

const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const flush = () => new Promise((resolve) => setImmediate(resolve));
const audio = () => ({ audioBuffer: Buffer.from("test audio"), mimeType: "audio/wav", synthesisRevision: "r1" });

test("cancel a promoted waiter without cancelling shared work or submitting a duplicate", async (t) => {
  const { service } = await isolatedService(t);
  service.coordinator.getOrFetchSynthesisRevision = async () => "r1";
  const shared = deferred();
  service.coordinator.promoteJob = () => shared.promise;
  let direct = 0;
  service.synthesizeConfigured = async () => { direct++; return audio(); };
  const controller = new AbortController();
  const request = service.synthesize("hello", controller.signal);
  await flush();
  controller.abort(new DOMException("Stopped", "AbortError"));
  await assert.rejects(request, { name: "AbortError" });
  assert.equal(service.coordinator.foregroundRequests, 0);
  shared.resolve(audio());
  await flush();
  assert.equal(direct, 0);
});

test("a failed promoted synthesis is not silently submitted again", async (t) => {
  const { service } = await isolatedService(t);
  service.coordinator.getOrFetchSynthesisRevision = async () => "r1";
  service.coordinator.promoteJob = () => Promise.reject(new Error("backend outcome unknown"));
  let direct = 0;
  service.synthesizeConfigured = async () => { direct++; return audio(); };
  await assert.rejects(service.synthesize("hello"), /backend outcome unknown/);
  assert.equal(direct, 0);
});

test("simultaneous manual requests share synthesis and one cancellation preserves the other", async (t) => {
  const { service } = await isolatedService(t);
  service.coordinator.getOrFetchSynthesisRevision = async () => "r1";
  const synthesis = deferred();
  let calls = 0;
  let backendSignal;
  service.synthesizeConfigured = (text, signal) => { calls++; backendSignal = signal; return synthesis.promise; };
  const controller = new AbortController();
  const first = service.synthesize("shared", controller.signal);
  const second = service.synthesize("shared");
  await flush();
  assert.equal(calls, 1);
  controller.abort(new DOMException("Stopped", "AbortError"));
  await assert.rejects(first, { name: "AbortError" });
  assert.equal(backendSignal.aborted, false);
  synthesis.resolve(audio());
  assert.equal((await second).audioBase64, audio().audioBuffer.toString("base64"));
  assert.equal(service.foregroundJobs.size, 0);
  assert.equal(service.coordinator.foregroundRequests, 0);
});

test("cancelled last consumer drains admitted work before starting pending speculation", async (t) => {
  const { service } = await isolatedService(t);
  service.coordinator.getOrFetchSynthesisRevision = async () => "r1";
  const synthesis = deferred();
  service.synthesizeConfigured = () => synthesis.promise;
  const controller = new AbortController();
  const request = service.synthesize("shared", controller.signal);
  await flush();
  let background = 0;
  service.coordinator.scheduleSessionCandidate("other", { key: "other", run: async () => { background++; } });
  controller.abort(new DOMException("Stopped", "AbortError"));
  await assert.rejects(request, { name: "AbortError" });
  assert.equal(background, 0);
  assert.equal(service.foregroundJobs.size, 1);
  synthesis.resolve(audio());
  await flush();
  assert.equal(service.foregroundJobs.size, 0);
  assert.equal(service.coordinator.foregroundRequests, 0);
  assert.equal(background, 1);
});

test("late foreground result cannot repopulate a cache invalidated by settings", async (t) => {
  const { service } = await isolatedService(t);
  service.coordinator.getOrFetchSynthesisRevision = async () => "r1";
  const synthesis = deferred();
  service.synthesizeConfigured = () => synthesis.promise;
  const request = service.synthesize("hello");
  await flush();
  service.cache.clear();
  synthesis.resolve(audio());
  await request;
  assert.equal(service.cache.entryCount, 0);
});

test("settings reset does not join an old foreground admission with the same text", async (t) => {
  const { service } = await isolatedService(t);
  service.coordinator.getOrFetchSynthesisRevision = async () => "r1";
  const requests = [];
  service.synthesizeConfigured = () => { const item = deferred(); requests.push(item); return item.promise; };
  const oldRequest = service.synthesize("hello");
  await flush();
  service.cache.clear();
  const newRequest = service.synthesize("hello");
  await flush();
  assert.equal(requests.length, 2);
  requests[0].resolve(audio());
  requests[1].resolve(audio());
  await Promise.all([oldRequest, newRequest]);
});

test("an already cancelled manual request performs no metadata or synthesis work", async (t) => {
  const { service } = await isolatedService(t);
  let calls = 0;
  service.coordinator.getOrFetchSynthesisRevision = async () => { calls++; return "r1"; };
  service.synthesizeConfigured = async () => { calls++; return audio(); };
  const controller = new AbortController();
  controller.abort(new DOMException("Stopped", "AbortError"));
  await assert.rejects(service.synthesize("hello", controller.signal), { name: "AbortError" });
  assert.equal(calls, 0);
});

test("manual metadata wait blocks new speculation even before browser lease arrives", async (t) => {
  const { service } = await isolatedService(t);
  const metadata = deferred();
  service.coordinator.getOrFetchSynthesisRevision = () => metadata.promise;
  service.synthesizeConfigured = async () => audio();
  const foreground = service.synthesize("hello");
  let background = 0;
  service.coordinator.scheduleSessionCandidate("other-chat", {
    key: "other", candidateGeneration: 1,
    run: async () => { background++; },
  });
  assert.equal(background, 0);
  metadata.resolve("r1");
  await foreground;
  await flush();
  assert.equal(background, 1);
});

test("cancel during metadata prevents subsequent synthesis", async (t) => {
  const { service } = await isolatedService(t);
  const metadata = deferred();
  const controller = new AbortController();
  let calls = 0;
  service.coordinator.getOrFetchSynthesisRevision = () => metadata.promise;
  service.synthesizeConfigured = async () => { calls++; return audio(); };
  const request = service.synthesize("hello", controller.signal);
  controller.abort(new DOMException("Stopped", "AbortError"));
  metadata.resolve("r1");
  await assert.rejects(request, { name: "AbortError" });
  assert.equal(calls, 0);
});
