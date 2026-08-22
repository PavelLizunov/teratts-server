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
});

test("client mounts strict Remote and reads it without inject deadlock", () => {
  assert.match(client, /await ctx\.remote\.\$mount\(REMOTE\)/);
  assert.match(client, /ctx\.get\("remote\.terattsVoice"\)/);
  assert.doesNotMatch(client, /inject = \["remote\.terattsVoice"/);
  assert.match(client, /mode:\s*"strict"/);
  assert.match(client, /AbortError/);
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
  assert.doesNotMatch(client, /\u{1F50A}|\u{23F9}|\u{23F3}/u);
});

test("host owns network configuration, timeout, voice, and token", () => {
  assert.match(host, /TypertRemoteService/);
  assert.match(host, /super\(ctx, "terattsVoice"\)/);
  assert.match(host, /endpoint:/);
  assert.match(host, /timeoutMs:/);
  assert.match(host, /voice:/);
  assert.match(host, /tokenEnv:/);
  assert.match(host, /credentials\.resolve/);
  assert.match(host, /AbortSignal\.timeout/);
  assert.match(host, /authorization/);
  assert.match(host, /fetch\(endpoint/);
  assert.doesNotMatch(host, /ctx\.handle/);
});

test("client runtime inject declares only available services", () => {
  assert.match(client, /const inject = \["remote", "slots"\]/);
});

test("package bundle inject avoids static shell modules", () => {
  const inject = packageJson.dsh.client.inject;
  for (const name of [
    "@deepseek-ai/dsh-client-runtime",
    "@deepseek-ai/dsh-api-remotes",
    "@deepseek-ai/dsh-client-ui-conversation",
  ]) {
    assert.ok(inject.includes(name), `missing bundle injection ${name}`);
  }
  assert.ok(!inject.includes("@deepseek-ai/dsh-client-ui-primitives"));
});
