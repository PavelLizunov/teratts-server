import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { isolatedService, runtime } from "./helpers/runtime.js";

const manifest = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
const { Context } = await import(`${runtime}/@deepseek-ai/cordis/lib/index.js`);
const { remoteMethods } = await import(`${runtime}/@deepseek-ai/dsh-typert-protocol/lib/index.js`);

test("all declared DSH peers match the actual target runtime", async () => {
  for (const [name, expected] of Object.entries(manifest.peerDependencies)) {
    if (!name.startsWith("@deepseek-ai/dsh-")) continue;
    const installed = JSON.parse(await readFile(`${runtime}/${name}/package.json`, "utf8"));
    assert.equal(installed.version, expected, name);
  }
});

test("Host imports, mounts and exposes its Remote methods with real Cordis", async (t) => {
  const { module } = await isolatedService(t);
  const ctx = new Context();
  const fork = await ctx.plugin(module, { endpoint: "http://127.0.0.1:8088" });
  t.after(() => fork.dispose());
  const service = ctx.get("terattsVoice");
  assert.ok(service);
  const methods = remoteMethods(service).map((marker) => marker.method);
  for (const method of ["synthesize", "acquireForeground", "renewForeground", "releaseForeground"]) {
    assert.ok(methods.includes(method), method);
  }
  assert.equal(service.current().prepareMode, "off");
});

test("Config owns effective values without invoking the removed Settings API", async (t) => {
  const { module } = await isolatedService(t);
  const ctx = new Context();
  ctx.provide("settings", new Proxy({}, {
    get(_target, key) {
      if (key === "installSection") throw new Error("Removed Settings API accessed");
      return undefined;
    },
  }));
  const fork = await ctx.plugin(module, {
    endpoint: "https://teratts.tail9fd337.ts.net", maxRetries: 0, voice: "ru_f2",
  });
  t.after(() => fork.dispose());
  const config = ctx.get("terattsVoice").current();
  assert.equal(config.endpoint, "https://teratts.tail9fd337.ts.net");
  assert.equal(config.maxRetries, 0);
  assert.equal(config.voice, "ru_f2");
});

test("configuration remount disposes old service and starts fresh caches", async (t) => {
  const { module } = await isolatedService(t);
  const ctx = new Context();
  const first = await ctx.plugin(module, { voice: "ru_f1" });
  const oldService = ctx.get("terattsVoice");
  const controller = new AbortController();
  oldService.foregroundJobs.set("test", { controller });
  await first.dispose();
  assert.equal(controller.signal.aborted, true);
  assert.equal(ctx.get("terattsVoice"), undefined);
  const second = await ctx.plugin(module, { voice: "ru_f2", maxRetries: 0 });
  t.after(() => second.dispose());
  const next = ctx.get("terattsVoice");
  assert.notEqual(next, oldService);
  assert.equal(next.current().voice, "ru_f2");
  assert.equal(next.current().maxRetries, 0);
  assert.equal(next.foregroundJobs.size, 0);
});

test("plugin does not require Settings service to mount", async (t) => {
  const { module } = await isolatedService(t);
  const ctx = new Context();
  const fork = await ctx.plugin(module, {});
  t.after(() => fork.dispose());
  assert.equal(ctx.get("terattsVoice").current().endpoint, "http://127.0.0.1:8088");
});

test("shadow preparation does not block the speculative audio candidate", async (t) => {
  const { module, service, config } = await isolatedService(t, { prepareMode: "shadow" });
  let finishPrepare;
  let scheduledText;
  service.prepareText = () => new Promise((resolve) => { finishPrepare = resolve; });
  service.coordinator.getOrFetchSynthesisRevision = async () => "r1";
  service.coordinator.scheduleSessionCandidate = (_id, candidate) => { scheduledText = candidate.text; };
  const listener = module.preparationListener(service, () => config);
  const message = { id: "m1", role: "assistant", content: [{ type: "text", text: "# Заголовок\n\nПараграф ответа" }] };
  const session = { id: "test", deriveMessages: () => [message] };
  await listener(session, { type: "assistant/message", data: { turn: 1, message } });
  await listener(session, { type: "turn/end", data: { turn: 1, reason: { kind: "completed" } } });
  assert.equal(scheduledText, "Заголовок. Параграф ответа");
  assert.equal(typeof finishPrepare, "function");
  finishPrepare({ text: "Подготовлено", preparationRevision: "p1" });
});
