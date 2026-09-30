import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import test from "node:test";

const source = await readFile(new URL("../lib/client.js", import.meta.url), "utf8");

function loadClient() {
  let registration;
  const context = vm.createContext({
    window: { __ModuleLoader__: { load(value) { registration = value; } } },
    console, AbortController, setTimeout, clearTimeout, setInterval, clearInterval,
  });
  vm.runInContext(source, context);
  assert.equal(registration.id, "dsh-client-ui-teratts");
  const requested = [];
  const plugin = registration.factory((name) => {
    requested.push(name);
    if (name === "react") return {};
    throw new Error(`Unsupported module: ${name}`);
  });
  return { context, plugin, requested };
}

test("Remote descriptors register with the real current Typert Registry", async () => {
  const { runtime } = await import("./helpers/runtime.js");
  const { Context } = await import(`${runtime}/@deepseek-ai/cordis/lib/index.js`);
  const { default: Registry } = await import(`${runtime}/@deepseek-ai/dsh-typert-registry/lib/index.js`);
  const ctx = new Context();
  const registry = new Registry(ctx);
  const { plugin } = loadClient();
  let contribution;
  const dispose = await plugin.apply({
    remote: { async $mount(value) { contribution = value; return () => {}; } },
    get: () => ({}),
    slots: { inject: () => () => {} },
  });
  try {
    const unregister = registry.remotes.register(contribution);
    assert.equal(registry.remotes.list().length, 6);
    await unregister();
  } finally {
    await dispose();
    await ctx.fiber.dispose();
  }
});

test("real Client Gateway mounts descriptors, calls synthesis and withdraws the namespace", async () => {
  const { runtime } = await import("./helpers/runtime.js");
  const cordis = await import(`${runtime}/@deepseek-ai/cordis/lib/index.js`);
  const { default: Registry } = await import(`${runtime}/@deepseek-ai/dsh-typert-registry/lib/index.js`);
  let gatewayRegistration;
  vm.runInNewContext(await readFile(`${runtime}/@deepseek-ai/dsh-api-gateway/lib/client.js`, "utf8"), {
    window: { __ModuleLoader__: { load(value) { gatewayRegistration = value; } } },
    console, crypto: globalThis.crypto, AbortController, AbortSignal, setTimeout, clearTimeout, setInterval, clearInterval,
  });
  const gateway = gatewayRegistration.factory((name) => {
    assert.equal(name, "@deepseek-ai/cordis");
    return cordis;
  });
  const ctx = new cordis.Context();
  new Registry(ctx);
  const calls = [];
  ctx.provide("connection", {
    start: () => ({ stop() {} }),
    registerGenerationSource: () => () => {},
    rpc: {
      open() { throw new Error("Unexpected stream"); },
      async call(path, endpoint, payload) {
        calls.push({ path, endpoint, payload });
        return { ok: true, value: { audioBase64: "wav", mimeType: "audio/wav" } };
      },
    },
  });
  ctx.provide("slots", { inject: () => () => {} });
  const gatewayFiber = await ctx.plugin(gateway);
  let ttsFiber;
  try {
    ttsFiber = await ctx.plugin(loadClient().plugin);
    const voice = ctx.get("remote.terattsVoice");
    assert.ok(voice, "real Gateway creates the voice namespace");
    const result = await voice.synthesize("Проверка", new AbortController().signal);
    assert.equal(result.ok, true);
    assert.equal(result.value.audioBase64, "wav");
    assert.equal(calls[0].endpoint, "terattsVoice/synthesize");
    assert.equal(calls[0].payload.args.text, "Проверка");
    await ttsFiber.dispose();
    assert.equal(ctx.get("remote.terattsVoice"), undefined);
  } finally {
    await ttsFiber?.dispose();
    await gatewayFiber.dispose();
    await ctx.fiber.dispose();
  }
});

test("mount failures propagate before registering any action", async () => {
  const { plugin } = loadClient();
  let registered = false;
  await assert.rejects(plugin.apply({
    remote: { $mount() { throw new Error("Invalid descriptor"); } },
    slots: { inject() { registered = true; } },
  }), /Invalid descriptor/);
  assert.equal(registered, false);
});

test("client factory loads without private DSH modules or DOM side effects", () => {
  const { plugin, requested } = loadClient();
  assert.equal(typeof plugin.apply, "function");
  assert.deepEqual(requested, ["react"]);
});

test("RemoteResult success unwraps business values, including lease rejection", async () => {
  const { context } = loadClient();
  context.response = { ok: true, value: { audioBase64: "wav", mimeType: "audio/wav" } };
  assert.deepEqual(vm.runInContext("unwrapRemoteResult(response)", context), context.response.value);
  context.response = { ok: true, value: { ok: false, reason: "expired" } };
  assert.deepEqual(vm.runInContext("unwrapRemoteResult(response)", context), context.response.value);
});

test("RemoteResult errors become failures instead of malformed audio", () => {
  const { context } = loadClient();
  context.response = { ok: false, error: { code: "gateway/internal", message: "Speech unavailable" } };
  assert.throws(() => vm.runInContext("unwrapRemoteResult(response)", context), /Speech unavailable/);
  context.response = { audioBase64: "unwrapped old API" };
  assert.throws(() => vm.runInContext("unwrapRemoteResult(response)", context), /Invalid TeraTTS RPC result/);
});
