import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { encodePrivateRecord, privateIngestUrl, PrivateTelemetry } from "../lib/private-telemetry.js";

function decode(body) {
  const size = body.readUInt32BE();
  return JSON.parse(body.subarray(4, 4 + size));
}

test("private destinations reject public hosts credentials and query", () => {
  assert.equal(privateIngestUrl(""), null);
  assert.equal(privateIngestUrl("http://100.110.84.30:10003/record"), "http://100.110.84.30:10003/record");
  for (const url of ["https://example.com/record", "http://192.168.0.1/record",
    "http://user:pass@100.110.84.30/record", "http://100.110.84.30/record?token=a"]) {
    assert.throws(() => privateIngestUrl(url));
  }
});

test("binary record preserves original unredacted text and media", () => {
  const body = encodePrivateRecord({ text: "Иван, мой телефон 123" }, { "synthesized.wav": Buffer.from([0, 255]) });
  const data = decode(body);
  assert.equal(data.metadata.text, "Иван, мой телефон 123");
  assert.deepEqual(data.attachments, [{ name: "synthesized.wav", size: 2 }]);
  assert.deepEqual(body.subarray(body.length - 2), Buffer.from([0, 255]));
});

test("telemetry disabled and failure isolation", async () => {
  const off = new PrivateTelemetry("", () => { throw Error("never"); });
  assert.equal((await off.record({ draft: "private" })).status, "disabled");
  const fail = new PrivateTelemetry("http://127.0.0.1:10003/record", () => { throw Error("unavailable"); });
  assert.equal((await fail.record({ draft: "private" })).status, "dropped");
  assert.equal(fail.pending, 0);
});

test("bounded pending records and exact settings transmitted", async () => {
  let release;
  const seen = [];
  const record = new PrivateTelemetry("http://127.0.0.1:10003/record", async (_url, request) => {
    seen.push(decode(request.body));
    await new Promise((resolve) => { release = resolve; });
    return { ok: true, json: async () => ({ sample_id: "sample" }) };
  });
  const pending = record.record({ sessionId: "s", messageId: "m", text: "original" });
  record.pending = 4;
  assert.equal((await record.record({})).reason, "queue_full");
  release();
  assert.equal((await pending).sampleId, "sample");
  assert.equal(seen[0].metadata.text, "original");
});

test("client uses supported composer hook and observed playback context", async () => {
  const client = await readFile(new URL("../lib/client.js", import.meta.url), "utf8");
  assert.match(client, /useInput\(\(value\) => value\)/);
  assert.match(client, /conversation\.input\.above/);
  assert.match(client, /event: "composer_draft"/);
  assert.match(client, /event: "playback_state"/);
  assert.match(client, /synthesizeObserved\(chunk,/);
  assert.doesNotMatch(client, /document\.querySelector.*textarea/);
});
