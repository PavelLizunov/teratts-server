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
