import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
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

// Extract helper functions for runnable verification
const fnSource = host
  .slice(
    host.indexOf("function isLoopbackHost"),
    host.indexOf("const remoteInitializers = [];"),
  )
  .replace(/export\s+/g, "");

const helpers = {};
const factory = new Function(
  "exports",
  "Buffer",
  "URL",
  "Number",
  "Date",
  "Math",
  "Error",
  "console",
  "const MAX_RESPONSE_BYTES = 16 * 1024 * 1024;\n" +
    fnSource +
    "\nexports.validateAndResolveEndpoint = validateAndResolveEndpoint;\nexports.parseRetryAfter = parseRetryAfter;\nexports.readAudioResponse = readAudioResponse;\nexports.MAX_RESPONSE_BYTES = MAX_RESPONSE_BYTES;\nexports.isLoopbackHost = isLoopbackHost;",
);
factory(helpers, Buffer, URL, Number, Date, Math, Error, console);

const { validateAndResolveEndpoint, parseRetryAfter, readAudioResponse, MAX_RESPONSE_BYTES } =
  helpers;

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

test("host pins request language and sends plain text", () => {
  assert.match(host, /language,/);
  assert.match(host, /language: s\.string\(\)\.default\("ru"\)/);
  assert.match(host, /config\.language === "en" \? "en" : "ru"/);
  assert.doesNotMatch(host, /tagForeignRuns/);
});

test("host exposes stress toggle defaulting to suflyor parity (off)", () => {
  assert.match(host, /stress: s\.boolean\(\)\.default\(false\)/);
  assert.match(host, /russian_stress: config\.stress === true/);
  assert.match(host, /stress: config\.stress \?\? false/);
  assert.match(host, /speechFront: s\.boolean\(\)\.default\(true\)/);
  assert.match(host, /speech_front: config\.speechFront !== false/);
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

test("host endpoint validation allows http loopback and preserves subpaths", () => {
  assert.equal(
    validateAndResolveEndpoint("http://127.0.0.1:8088"),
    "http://127.0.0.1:8088/tts",
  );
  assert.equal(
    validateAndResolveEndpoint("http://127.0.0.1:8088/"),
    "http://127.0.0.1:8088/tts",
  );
  assert.equal(
    validateAndResolveEndpoint("http://localhost:8088"),
    "http://localhost:8088/tts",
  );
  assert.equal(
    validateAndResolveEndpoint("http://127.0.0.2:8088"),
    "http://127.0.0.2:8088/tts",
  );
  assert.equal(
    validateAndResolveEndpoint("http://[::1]:8088"),
    "http://[::1]:8088/tts",
  );
  assert.equal(
    validateAndResolveEndpoint("http://127.0.0.1:8088/api/v1"),
    "http://127.0.0.1:8088/api/v1/tts",
  );
  assert.equal(
    validateAndResolveEndpoint("http://127.0.0.1:8088/custom/sub/"),
    "http://127.0.0.1:8088/custom/sub/tts",
  );
});

test("host endpoint validation allows only exact TeraTTS tailnet host and preserves subpaths", () => {
  assert.equal(
    validateAndResolveEndpoint("https://teratts.tail9fd337.ts.net"),
    "https://teratts.tail9fd337.ts.net/tts",
  );
  assert.equal(
    validateAndResolveEndpoint("https://teratts.tail9fd337.ts.net/prefix"),
    "https://teratts.tail9fd337.ts.net/prefix/tts",
  );
});

test("host endpoint validation rejects SSRF targets and insecure non-loopback http", () => {
  assert.throws(
    () => validateAndResolveEndpoint("http://teratts.tail9fd337.ts.net"),
    /TeraTTS endpoint is not allowed/,
  );
  assert.throws(
    () => validateAndResolveEndpoint("https://windows-brat.tail9fd337.ts.net"),
    /TeraTTS endpoint is not allowed/,
  );
  assert.throws(
    () => validateAndResolveEndpoint("https://sub.teratts.tail9fd337.ts.net"),
    /TeraTTS endpoint is not allowed/,
  );
  assert.throws(
    () => validateAndResolveEndpoint("http://192.168.1.100:8088"),
    /TeraTTS endpoint is not allowed/,
  );
  assert.throws(
    () => validateAndResolveEndpoint("http://10.0.0.1:8088"),
    /TeraTTS endpoint is not allowed/,
  );
  assert.throws(
    () => validateAndResolveEndpoint("https://evil.com"),
    /TeraTTS endpoint is not allowed/,
  );
  assert.throws(
    () => validateAndResolveEndpoint("https://eviltail9fd337.ts.net"),
    /TeraTTS endpoint is not allowed/,
  );
  assert.throws(
    () => validateAndResolveEndpoint("https://attacker.ts.net"),
    /TeraTTS endpoint is not allowed/,
  );
  assert.throws(
    () => validateAndResolveEndpoint("not a valid url"),
    /Invalid TeraTTS endpoint URL/,
  );
});

test("host validates endpoint before credential resolution to prevent bearer leakage", () => {
  const validatePos = host.indexOf("validateAndResolveEndpoint(config.endpoint)");
  const resolvePos = host.indexOf("credentials.resolve(");
  assert.ok(validatePos !== -1, "validateAndResolveEndpoint must be called");
  assert.ok(resolvePos !== -1, "credentials.resolve must be called");
  assert.ok(
    validatePos < resolvePos,
    "endpoint validation must occur before credential resolution",
  );
});

test("host parses Retry-After header and retry_after_ms JSON body", () => {
  const respSeconds = {
    headers: new Map([["retry-after", "3"]]),
  };
  respSeconds.headers.get = (k) => respSeconds.headers.get?.(k) ?? respSeconds.headers.entries?.();
  // Standard Map wrapper for header lookup
  const makeHeaders = (obj) => ({
    headers: {
      get(k) {
        return obj[k.toLowerCase()] ?? null;
      },
    },
  });

  assert.equal(parseRetryAfter(makeHeaders({ "retry-after": "5" }), null), 5000);
  assert.equal(parseRetryAfter(makeHeaders({ "retry-after": "1.5" }), null), 1500);
  assert.equal(
    parseRetryAfter(makeHeaders({}), { retry_after_ms: 1200 }),
    1200,
  );
  assert.equal(
    parseRetryAfter(makeHeaders({}), { retry_after: 4 }),
    4000,
  );
  assert.equal(parseRetryAfter(makeHeaders({}), null), undefined);
});

test("host rejects Content-Length above 16 MiB", async () => {
  const fakeResponse = {
    headers: {
      get(k) {
        if (k.toLowerCase() === "content-length") return String(17 * 1024 * 1024);
        return null;
      },
    },
  };
  await assert.rejects(
    () => readAudioResponse(fakeResponse),
    /TeraTTS response size exceeded 16 MiB limit/,
  );
});

test("host enforces streaming byte limit when Content-Length is absent", async () => {
  let canceled = false;
  const largeChunk = new Uint8Array(9 * 1024 * 1024); // 9 MiB
  let chunkCount = 0;

  const fakeResponse = {
    headers: {
      get() {
        return null;
      },
    },
    body: {
      getReader() {
        return {
          async read() {
            chunkCount += 1;
            if (chunkCount <= 2) {
              return { done: false, value: largeChunk };
            }
            return { done: true, value: undefined };
          },
          async cancel() {
            canceled = true;
          },
        };
      },
    },
  };

  await assert.rejects(
    () => readAudioResponse(fakeResponse),
    /TeraTTS response size exceeded 16 MiB limit/,
  );
  assert.equal(canceled, true, "stream reader should be canceled on limit overflow");
});

test("host reads audio within 16 MiB and rejects empty audio", async () => {
  const smallChunk = new Uint8Array([1, 2, 3, 4]);
  let chunkSent = false;
  const fakeResponse = {
    headers: {
      get() {
        return null;
      },
    },
    body: {
      getReader() {
        return {
          async read() {
            if (!chunkSent) {
              chunkSent = true;
              return { done: false, value: smallChunk };
            }
            return { done: true, value: undefined };
          },
          async cancel() {},
        };
      },
    },
  };

  const buffer = await readAudioResponse(fakeResponse);
  assert.equal(buffer.length, 4);

  const emptyResponse = {
    headers: {
      get() {
        return null;
      },
    },
    body: {
      getReader() {
        return {
          async read() {
            return { done: true, value: undefined };
          },
          async cancel() {},
        };
      },
    },
  };
  await assert.rejects(
    () => readAudioResponse(emptyResponse),
    /TeraTTS returned empty audio/,
  );
});

test("host sanitizes client errors and avoids leaking endpoint or cause details", () => {
  // Client errors should not include template literal variables for endpoint or internal cause
  assert.doesNotMatch(host, /throw new Error\([^)]*\$\{endpoint\}/);
  assert.doesNotMatch(host, /throw new Error\([^)]*cause \$\{cause/);
  // Host logger records details for diagnostics
  assert.match(host, /console\.error\(`\[teratts\] fetch to \$\{endpoint\} failed:`, error\)/);
  assert.match(host, /console\.error\(`\[teratts\] request failed with HTTP \$\{response\.status\}:`/);
});
