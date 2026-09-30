import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import { isolatedService } from "./helpers/runtime.js";

function clientFactory() {
  return readFile(new URL("../lib/client.js", import.meta.url), "utf8").then((source) => {
    let registration;
    vm.runInNewContext(source, { window: { __ModuleLoader__: { load: (value) => { registration = value; } } } });
    return registration;
  });
}

test("observed synthesis uses actual coordinator and preserves lease cleanup", async (t) => {
  const { service } = await isolatedService(t);
  const records = [];
  service.telemetry.record = async (metadata, files) => { records.push({ metadata, files }); return { status: "saved" }; };
  service.coordinator.getOrFetchSynthesisRevision = async () => "r1";
  service.synthesizeConfigured = async (_text, _signal, _config, _key, context) => {
    assert.equal(context.sessionId, "s");
    assert.equal(context.messageId, "m");
    return { audioBuffer: Buffer.from("exact-original-audio"), mimeType: "audio/wav", synthesisRevision: "r1" };
  };
  const first = await service.synthesizeObserved("hello", { sessionId: "s", messageId: "m" });
  const second = await service.synthesizeObserved("hello", { sessionId: "s", messageId: "m" });
  assert.equal(first.audioBase64, second.audioBase64);
  assert.equal(service.coordinator.foregroundRequests, 0);
  assert.equal(records.filter((record) => record.metadata.kind === "tts_client_result").length, 2);
  assert.equal(records.at(-1).metadata.cacheHit, true);
});

test("draft observer mounts with real registered hook names and session state", async () => {
  const entry = await clientFactory();
  const events = [];
  const effects = [];
  const registrations = [];
  const React = {
    createElement: (component, props) => ({ component, props }),
    useEffect: (effect) => effects.push(effect),
  };
  const exports = entry.factory((name) => { if (name === "react") return React; throw Error(name); });
  const remote = { recordTelemetry: async (event) => { events.push(event); return { ok: true, value: { status: "saved" } }; } };
  const ctx = {
    remote: { $mount: async () => () => {} },
    get: (name) => name === "remote.terattsVoice" ? remote : undefined,
    slots: {
      inject: (_name, callback) => callback(),
      register: (config, render) => { registrations.push({ config, render }); return () => {}; },
    },
  };
  const dispose = await exports.apply(ctx);
  const draft = registrations.find(({ config }) => config.id === "teratts-private-draft-telemetry");
  assert.ok(draft);
  const node = draft.render({ useInput: (select) => select({ draft: "Иван, мой черновик", draftRev: 3 }),
    useSession: (select) => select({ id: "exact-session" }) });
  node.component(node.props);
  for (const effect of effects) effect();
  await Promise.resolve();
  assert.equal(events[0].draft, "Иван, мой черновик");
  assert.equal(events[0].sessionId, "exact-session");
  assert.equal(events[0].inputState.draftRev, 3);
  await dispose();
});
