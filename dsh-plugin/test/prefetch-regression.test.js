import assert from "node:assert/strict";
import test from "node:test";
import { isolatedService } from "./helpers/runtime.js";

const flush = () => new Promise((resolve) => setImmediate(resolve));
function events(module, service, config) {
  const listener = module.preparationListener(service, () => config);
  const message = { id: "message", role: "assistant", content: [{ type: "text", text: "Привет." }] };
  const session = { id: "chat", deriveMessages: () => [message] };
  const finish = async () => {
    await listener(session, { type: "assistant/message", data: { message, turn: 1 } });
    await listener(session, { type: "turn/end", data: { turn: 1, reason: { kind: "completed" } } });
    await flush();
  };
  return { listener, session, finish };
}

test("first prefetched audio is reused after foreground discovers the server revision", async (t) => {
  const { service, config, module } = await isolatedService(t);
  service.coordinator.getOrFetchSynthesisRevision = async () => "r1";
  let calls = 0;
  service.synthesizeConfigured = async () => { calls++; return { audioBuffer: Buffer.from("audio"), mimeType: "audio/wav", synthesisRevision: "r1" }; };
  const { finish } = events(module, service, config);
  await finish();
  assert.equal(calls, 1);
  await service.synthesize("Привет.");
  assert.equal(calls, 1, "revision discovery must not discard usable first-fragment prefetch");
});

test("new turn during metadata lookup prevents late speculative scheduling", async (t) => {
  const { service, config, module } = await isolatedService(t);
  let finishMetadata;
  service.coordinator.getOrFetchSynthesisRevision = () => new Promise((resolve) => { finishMetadata = resolve; });
  let calls = 0;
  service.synthesizeConfigured = async () => { calls++; return { audioBuffer: Buffer.from("audio"), synthesisRevision: "r1" }; };
  const { finish, listener, session } = events(module, service, config);
  const pending = finish();
  await flush();
  await listener(session, { type: "turn/start", data: { turn: 2 } });
  finishMetadata("r1");
  await pending;
  assert.equal(calls, 0);
  assert.equal(service.coordinator.sessionCandidates.size, 0);
});

test("settings invalidation prevents old queued speculative config from running", async (t) => {
  const { service, config, module } = await isolatedService(t);
  service.coordinator.getOrFetchSynthesisRevision = async () => "r1";
  service.coordinator.suspendSpeculation("test-queue");
  let calls = 0;
  service.synthesizeConfigured = async () => { calls++; return { audioBuffer: Buffer.from("audio"), synthesisRevision: "r1" }; };
  const { finish } = events(module, service, config);
  await finish();
  service.cache.clear();
  service.coordinator.resetSpeculationSuspensionAdmin("test");
  await flush();
  assert.equal(calls, 0);
});

test("starting a new turn removes an obsolete pending speculative candidate", async (t) => {
  const { service, config, module } = await isolatedService(t);
  service.coordinator.getOrFetchSynthesisRevision = async () => "r1";
  service.coordinator.suspendSpeculation("test-queue");
  const { finish, listener, session } = events(module, service, config);
  await finish();
  assert.equal(service.coordinator.sessionCandidates.size, 1);
  await listener(session, { type: "turn/start", data: { turn: 2 } });
  assert.equal(service.coordinator.sessionCandidates.size, 0);
});
