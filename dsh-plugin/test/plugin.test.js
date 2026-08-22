import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const clientPath = new URL("../lib/client.js", import.meta.url);
const hostPath = new URL("../lib/index.js", import.meta.url);
const packagePath = new URL("../package.json", import.meta.url);

const [client, host, packageRaw] = await Promise.all([
  readFile(clientPath, "utf8"),
  readFile(hostPath, "utf8"),
  readFile(packagePath, "utf8"),
]);
const packageJson = JSON.parse(packageRaw);

test("client contains no direct TTS endpoint or credential handling", () => {
  assert.doesNotMatch(client, /tail9fd337|windows-brat|127\.0\.0\.1|TERATTS_TOKEN/);
  assert.doesNotMatch(client, /fetch\s*\(/);
  assert.match(client, /ctx\.remote\.terattsVoice/);
});

test("Remote descriptor uses rc.8 strict codecs and lifecycle cleanup", () => {
  assert.doesNotMatch(client, /src-json/);
  assert.equal((client.match(/mode:\s*"strict"/g) || []).length, 2);
  assert.match(client, /schema:\s*textSchema/);
  assert.match(client, /schema:\s*audioSchema/);
  assert.match(client, /const disposeRemote = await ctx\.remote\.\$mount/);
  assert.match(client, /await disposeRemote\(\)/);
  assert.match(client, /disposeSlot\(\)/);
  assert.match(client, /error\?\.code === "cancelled"/);
});

test("client uses required playback and accessible UI primitives", () => {
  assert.match(client, /IconLoadingOutline16/);
  assert.match(client, /IconStopFill16/);
  assert.match(client, /Tooltip/);
  assert.match(client, /Toast/);
  assert.match(client, /stroke:\s*"currentColor"/);
  assert.match(client, /"aria-busy"/);
  assert.doesNotMatch(client, /"aria-pressed"/);
  assert.match(client, /playback\.epoch/);
  assert.match(client, /playback\.owner/);
  assert.match(client, /URL\.revokeObjectURL/);
  assert.doesNotMatch(client, /🔊|⏹|⏳/u);
});

test("host owns network configuration, timeout, voice, and token", () => {
  assert.match(host, /endpoint:/);
  assert.match(host, /timeoutMs:/);
  assert.match(host, /voice:/);
  assert.match(host, /tokenEnv:/);
  assert.match(host, /credentials\.resolve/);
  assert.match(host, /AbortSignal\.timeout/);
  assert.match(host, /authorization/);
  assert.match(host, /fetch\(endpoint/);
});

test("client dependency graph includes every dynamic package", () => {
  const inject = packageJson.dsh.client.inject;
  for (const name of [
    "@deepseek-ai/dsh-client-runtime",
    "@deepseek-ai/dsh-api-remotes",
    "@deepseek-ai/dsh-client-ui-conversation",
  ]) {
    assert.ok(inject.includes(name), `missing client injection ${name}`);
  }
  assert.ok(
    !inject.includes("@deepseek-ai/dsh-client-ui-primitives"),
    "static shell modules must not be declared as dynamic plugin injections",
  );
});
