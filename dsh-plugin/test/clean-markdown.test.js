import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

// Provide minimal environment for evaluating client bundle in Node
let registeredEntry = null;
if (typeof window === "undefined") {
  globalThis.window = {
    __ModuleLoader__: {
      load: (entry) => {
        registeredEntry = entry;
      },
    },
  };
  globalThis.document = {
    querySelector: () => null,
    createElement: () => ({ dataset: {} }),
    head: { appendChild: () => {} },
  };
}

await import("../lib/client.js");
const cleanMarkdown = globalThis.__teratts_cleanMarkdown;
const PLAYBACK_RATES = globalThis.__teratts_PLAYBACK_RATES;
const nextPlaybackRate = globalThis.__teratts_nextPlaybackRate;
const clampSeekTime = globalThis.__teratts_clampSeekTime;
const splitSpeechText = globalThis.__teratts_splitSpeechText;
const inspectMonoPcmWav = globalThis.__teratts_inspectMonoPcmWav;
const locateBufferedTime = globalThis.__teratts_locateBufferedTime;
const technicalMarkdown = await readFile(
  new URL("./fixtures/technical-markdown.md", import.meta.url),
  "utf8",
);

test("client helpers are exposed for tests", () => {
  assert.equal(typeof cleanMarkdown, "function");
  assert.equal(typeof nextPlaybackRate, "function");
  assert.equal(typeof clampSeekTime, "function");
  assert.equal(typeof splitSpeechText, "function");
  assert.equal(typeof inspectMonoPcmWav, "function");
  assert.equal(typeof locateBufferedTime, "function");
});

test("preserves exact <ru> and <en> language tags while stripping generic HTML", () => {
  assert.equal(
    cleanMarkdown("<ru>Привет, мир!</ru>"),
    "<ru>Привет, мир!</ru>",
  );
  assert.equal(
    cleanMarkdown("<en>Hello world!</en>"),
    "<en>Hello world!</en>",
  );
  assert.equal(
    cleanMarkdown("<ru>Это русский текст</ru> and <en>this is English text</en>"),
    "<ru>Это русский текст</ru> and <en>this is English text</en>",
  );
  assert.equal(
    cleanMarkdown("<div class=\"box\"><p><b>Bold</b> <ru>текст</ru> <span>span</span></p></div>"),
    "Bold <ru>текст</ru> span",
  );
  assert.equal(
    cleanMarkdown("Text with <rumor>fake tag</rumor> and <enter>another</enter> and <en>real</en>"),
    "Text with fake tag and another and <en>real</en>",
  );
});

test("replaces underscores in snake_case identifiers with word boundaries instead of concatenating", () => {
  assert.equal(
    cleanMarkdown("Call `get_user_by_id` with `user_account_token`"),
    "Call get user by id with user account token",
  );
  assert.equal(
    cleanMarkdown("The variable snake_case_identifier should not become snakecaseidentifier"),
    "The variable snake case identifier should not become snakecaseidentifier",
  );
  assert.equal(
    cleanMarkdown("MY_GLOBAL_CONSTANT and __init__"),
    "MY GLOBAL CONSTANT and init",
  );
  assert.equal(
    cleanMarkdown("*italic_text_with_underscores*"),
    "italic text with underscores",
  );
});

test("processes table cells through cleanLine and ignores separator rows", () => {
  const markdownTable = [
    "| Param | Description | Default |",
    "| :--- | :--- | :--- |",
    "| `api_key` | <ru>Ключ доступа</ru> | `secret_123` |",
    "| **timeout_ms** | [Docs](https://example.com) | 5000 |",
  ].join("\n");

  assert.equal(
    cleanMarkdown(markdownTable),
    "Param, Description, Default. api key, <ru>Ключ доступа</ru>, secret 123. timeout ms, Docs, 5000.",
  );
});

test("reads fenced blocks and cleans inline code", () => {
  const fenced = [
    "Here is an example:",
    "```typescript",
    "function calculate_sum(a_val: number, b_val: number) {",
    "  return a_val + b_val;",
    "}",
    "```",
    "End of example.",
  ].join("\n");

  assert.equal(
    cleanMarkdown(fenced),
    "Here is an example: function calculate sum a val: number, b val: number. return a val + b val. End of example.",
  );

  assert.equal(
    cleanMarkdown("Inline `code_block_var` test"),
    "Inline code block var test",
  );
});

test("preserves '5 с половиной' without greedy seconds expansion", () => {
  assert.equal(
    cleanMarkdown("Это заняло 5 с половиной часов"),
    "Это заняло 5 с половиной часов",
  );
  assert.equal(
    cleanMarkdown("Подождите 2 с лишним минуты"),
    "Подождите 2 с лишним минуты",
  );
  assert.equal(
    cleanMarkdown("Выполните шаг 1 с параметрами по умолчанию"),
    "Выполните шаг 1 с параметрами по умолчанию",
  );
});

test("preserves '8.0с' and leaves unit expansion to speech-front", () => {
  assert.equal(
    cleanMarkdown("Время ответа составило 8.0с"),
    "Время ответа составило 8.0с",
  );
  assert.equal(
    cleanMarkdown("Задержка 12.5с или 10с"),
    "Задержка 12.5с или 10с",
  );
  assert.equal(
    cleanMarkdown("Таймаут 3.5 с"),
    "Таймаут 3.5 с",
  );
});

test("converts arrows and multiplication signs into language-neutral punctuation", () => {
  assert.equal(
    cleanMarkdown("Шаг 1 → Шаг 2 → Шаг 3"),
    "Шаг 1, Шаг 2, Шаг 3",
  );
  assert.equal(
    cleanMarkdown("Step A → Step B"),
    "Step A, Step B",
  );
  assert.equal(
    cleanMarkdown("Matrix dimensions 2 × 3"),
    "Matrix dimensions 2, 3",
  );
  assert.equal(
    cleanMarkdown("10 × 20 pixels"),
    "10, 20 pixels",
  );
  // Ensure no Russian words like 'даёт' or 'умножить' are injected into English/multilingual text
  assert.doesNotMatch(cleanMarkdown("Step 1 → Step 2 and 2 × 3"), /даёт|умножить/);
});

test("client plugin factory registers and exports only standard Cordis lifecycle functions", () => {
  assert.ok(registeredEntry !== null);
  assert.equal(registeredEntry.id, "dsh-client-ui-teratts");
  assert.equal(typeof registeredEntry.factory, "function");

  const mockRequire = (id) => {
    if (id === "react") return { createElement: () => ({}), useRef: () => ({}), useCallback: () => ({}) };
    if (id === "@deepseek-ai/dsh-client-ui-primitives") return {};
    return {};
  };

  const exports = registeredEntry.factory(mockRequire);
  assert.equal(typeof exports.apply, "function");
  assert.deepEqual(exports.inject, ["remote", "slots"]);
  assert.equal(Object.keys(exports).sort().join(","), "apply,inject");
});

test("converts comparison expressions into speakable text while preserving language tags", () => {
  assert.equal(cleanMarkdown("3 < 5 and 5 > 2"), "3 меньше 5 and 5 больше 2");
  assert.equal(cleanMarkdown("x <= y && z >= 0"), "x меньше или равно y && z больше или равно 0");
  assert.equal(cleanMarkdown("<ru>3 < 5</ru>"), "<ru>3 меньше 5</ru>");
});

test("preserves leading years while still stripping short ordered-list markers", () => {
  assert.equal(cleanMarkdown("1984. Роман Джорджа Оруэлла."), "1984. Роман Джорджа Оруэлла.");
  assert.equal(cleanMarkdown("2024. Это был хороший год."), "2024. Это был хороший год.");
  assert.equal(cleanMarkdown("12. Элемент списка"), "Элемент списка.");
});

test("handles markdown links with one level of parenthesized destinations", () => {
  assert.equal(
    cleanMarkdown("[Rust](https://en.wikipedia.org/wiki/Rust_(programming_language))"),
    "Rust",
  );
});

test("fenced code keeps speakable content without fence syntax", () => {
  assert.equal(
    cleanMarkdown("Before\n```js\nconst x = 1\n```\nAfter"),
    "Before const x = 1. After",
  );
});

test("technical spec keeps fenced YAML and removes checklist markers", () => {
  const cleaned = cleanMarkdown(technicalMarkdown);
  const contract = cleaned.slice(cleaned.indexOf("Interface / Data Contract"));
  const terms = [
    "pnpm-workspace:",
    "allowBuilds:",
    "node-pty: true",
    "better-sidebar:",
    "shell: /usr/bin/ssh",
    "shellArgs:",
    "PreferredAuthentications=password",
    "PubkeyAuthentication=no",
    "StrictHostKeyChecking=yes",
    "user@127.0.0.1",
    "sidebar-admin-sshd:",
    "authentication: PAM-password",
    "allowUsers: user",
    "permitRootLogin: false",
    "forwarding: false",
    "idleRootSession: PTY-owned",
  ];
  let previous = -1;
  for (const term of terms) {
    const index = contract.indexOf(term);
    assert.ok(index > previous, `${term} must be preserved in order`);
    previous = index;
  }
  assert.doesNotMatch(cleaned, /```|\[ \]|блок кода/);
  assert.match(cleaned, /pnpm rebuild node-pty создаёт Linux pty\.node\./);
});

test("technical spec uses a small first chunk without losing text", () => {
  const cleaned = cleanMarkdown(technicalMarkdown);
  const chunks = splitSpeechText(cleaned);
  assert.ok(chunks[0].length <= 240);
  assert.ok(chunks.slice(1).every((chunk) => chunk.length <= 800));
  assert.equal(chunks.join(" "), cleaned);

  const legacy = splitSpeechText(cleaned, 800);
  assert.deepEqual(legacy.map((chunk) => chunk.length), [773, 783, 589]);
  assert.equal(legacy.join(" "), cleaned);
  assert.throws(() => splitSpeechText(cleaned, 0), /invalid speech chunk size/);
});

test("long language spans split into independently balanced requests", () => {
  const tagged = `<ru>${"слово ".repeat(200).trim()}</ru> and <en>${"word ".repeat(200).trim()}</en>`;
  const chunks = splitSpeechText(tagged);
  assert.ok(chunks.length > 2);
  assert.ok(chunks[0].length <= 240);
  assert.ok(chunks.slice(1).every((chunk) => chunk.length <= 800));
  for (const chunk of chunks) {
    const opens = [...chunk.matchAll(/<(ru|en)>/g)].map((match) => match[1]);
    const closes = [...chunk.matchAll(/<\/(ru|en)>/g)].map((match) => match[1]);
    assert.deepEqual(closes, opens);
  }
  const spoken = (value) => value.replace(/<\/?(?:ru|en)>/g, "").replace(/\s+/g, " ").trim();
  assert.equal(spoken(chunks.join(" ")), spoken(tagged));
  assert.throws(() => splitSpeechText("<ru>незакрытый"), /unbalanced/);
  assert.throws(() => splitSpeechText("<ru><en>x</en></ru>"), /nested/);
});

function pcmWav(payload, sampleRate = 44_100) {
  const bytes = new Uint8Array(44 + payload.length);
  const view = new DataView(bytes.buffer);
  const tag = (offset, value) => {
    for (let index = 0; index < value.length; index += 1) {
      bytes[offset + index] = value.charCodeAt(index);
    }
  };
  tag(0, "RIFF");
  view.setUint32(4, bytes.length - 8, true);
  tag(8, "WAVE");
  tag(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  tag(36, "data");
  view.setUint32(40, payload.length, true);
  bytes.set(payload, 44);
  return bytes;
}

test("inspects WAV duration and locates a global buffered offset", () => {
  const wav = pcmWav(new Uint8Array(200), 10);
  const info = inspectMonoPcmWav(wav);
  assert.equal(info.dataBytes, 200);
  assert.equal(info.duration, 10);
  assert.deepEqual(locateBufferedTime([10, 20], 17), {
    index: 1,
    offset: 7,
    target: 17,
    total: 30,
  });
  assert.deepEqual(locateBufferedTime([10, 20], 99), {
    index: 1,
    offset: 20,
    target: 30,
    total: 30,
  });
  assert.equal(locateBufferedTime([], 5), null);
});

test("PLAYBACK_RATES contains exact rates [1, 1.25, 1.5, 2]", () => {
  assert.deepEqual(PLAYBACK_RATES, [1, 1.25, 1.5, 2]);
});

test("nextPlaybackRate cycles through PLAYBACK_RATES in order and loops around", () => {
  assert.equal(nextPlaybackRate(1), 1.25);
  assert.equal(nextPlaybackRate(1.25), 1.5);
  assert.equal(nextPlaybackRate(1.5), 2);
  assert.equal(nextPlaybackRate(2), 1);
  assert.equal(nextPlaybackRate(0), 1);
  assert.equal(nextPlaybackRate(undefined), 1);
  assert.equal(nextPlaybackRate("invalid"), 1);
});

test("clampSeekTime clamps seek target within [0, duration]", () => {
  assert.equal(clampSeekTime(10, -10, 30), 0);
  assert.equal(clampSeekTime(5, -10, 30), 0);
  assert.equal(clampSeekTime(20, 15, 30), 30);
  assert.equal(clampSeekTime(25, 15, 30), 30);
  assert.equal(clampSeekTime(10, 15, 30), 25);
  assert.equal(clampSeekTime(10, -5, 30), 5);
});

test("clampSeekTime is a no-op for non-finite or non-positive duration", () => {
  assert.equal(clampSeekTime(10, -10, NaN), 10);
  assert.equal(clampSeekTime(10, 15, 0), 10);
  assert.equal(clampSeekTime(10, 15, -5), 10);
  assert.equal(clampSeekTime(10, 15, Infinity), 10);
  assert.equal(clampSeekTime(10, 15, null), 10);
  assert.equal(clampSeekTime(10, 15, undefined), 10);
});

test("client source handles active-timeout cleanup and event propagation prevention", () => {
  assert.equal(typeof registeredEntry.factory, "function");
  const fnStr = registeredEntry.factory.toString();
  assert.match(fnStr, /locateBufferedTime/);
  assert.match(fnStr, /nextPlaybackRate/);
  assert.match(fnStr, /e\.stopPropagation\(\)/);
  assert.match(fnStr, /Request timed out/);
});

function createDeferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function setupPlaybackHarness() {
  const createdUrls = [];
  const revokedUrls = [];
  const audioInstances = [];
  const playDeferreds = [];
  const synthCalls = [];
  const originalCreate = globalThis.URL.createObjectURL;
  const originalRevoke = globalThis.URL.revokeObjectURL;
  const originalAudio = globalThis.Audio;

  globalThis.URL.createObjectURL = () => {
    const url = `blob:test-${createdUrls.length + 1}`;
    createdUrls.push(url);
    return url;
  };
  globalThis.URL.revokeObjectURL = (url) => revokedUrls.push(url);

  globalThis.Audio = class MockAudio {
    constructor(url) {
      this.src = url;
      this.playbackRate = 1;
      this.currentTime = 0;
      this.paused = true;
      this.ended = false;
      this.playCalls = 0;
      this.onended = null;
      this.onerror = null;
      audioInstances.push(this);
    }
    play() {
      this.playCalls += 1;
      this.paused = false;
      this.ended = false;
      if (this.deferNextPlay) {
        this.deferNextPlay = false;
        const deferred = createDeferred();
        playDeferreds.push(deferred);
        return deferred.promise;
      }
      return Promise.resolve();
    }
    pause() {
      this.paused = true;
    }
    removeAttribute(name) {
      if (name === "src") this.src = "";
    }
    load() {}
    finish() {
      this.paused = true;
      this.ended = true;
      this.onended?.();
    }
  };

  const voice = {
    synthesize(text, signal) {
      const deferred = createDeferred();
      synthCalls.push({ deferred, signal, text });
      return deferred.promise;
    },
  };
  const mockRequire = (id) => {
    if (id === "react") {
      return {
        createElement: () => ({}),
        Fragment: "Fragment",
        useCallback: (fn) => fn,
        useEffect: () => {},
        useRef: (value) => ({ current: value }),
        useState: (initial) => [typeof initial === "function" ? initial() : initial, () => {}],
      };
    }
    return {};
  };
  registeredEntry.factory(mockRequire);
  const api = globalThis.__teratts_playbackTestApi;

  return {
    api,
    audioInstances,
    createdUrls,
    playDeferreds,
    revokedUrls,
    synthCalls,
    voice,
    cleanup() {
      api.stopPlayback();
      if (originalCreate) globalThis.URL.createObjectURL = originalCreate;
      else delete globalThis.URL.createObjectURL;
      if (originalRevoke) globalThis.URL.revokeObjectURL = originalRevoke;
      else delete globalThis.URL.revokeObjectURL;
      if (originalAudio) globalThis.Audio = originalAudio;
      else delete globalThis.Audio;
    },
  };
}

const flushPromises = () => new Promise((resolve) => setImmediate(resolve));
const playbackWav = (sampleRate = 10) => ({
  audioBase64: Buffer.from(pcmWav(new Uint8Array(200), sampleRate)).toString("base64"),
  mimeType: "audio/wav",
});

test("first segment plays while later synthesis remains sequential", async () => {
  const harness = setupPlaybackHarness();
  try {
    const producer = harness.api.startPlayback(Symbol("owner"), "word ".repeat(100), harness.voice);
    assert.equal(harness.synthCalls.length, 1);
    assert.ok(harness.synthCalls[0].text.length <= 240);

    harness.synthCalls[0].deferred.resolve(playbackWav());
    await flushPromises();
    assert.equal(harness.audioInstances.length, 1);
    assert.equal(harness.audioInstances[0].playCalls, 1);
    assert.equal(harness.synthCalls.length, 2);
    assert.equal(harness.synthCalls[1].signal, harness.synthCalls[0].signal);

    harness.synthCalls[1].deferred.resolve(playbackWav());
    await producer;
    assert.equal(harness.audioInstances.length, 2);
    assert.equal(harness.audioInstances[1].playCalls, 0);

    harness.audioInstances[0].finish();
    await flushPromises();
    assert.equal(harness.audioInstances[1].playCalls, 1);
    assert.equal(harness.api.getPlayback().index, 1);
  } finally {
    harness.cleanup();
  }
});

test("global seek crosses buffered segments and rate propagates", async () => {
  const harness = setupPlaybackHarness();
  try {
    const producer = harness.api.startPlayback(Symbol("owner"), "word ".repeat(100), harness.voice);
    harness.synthCalls[0].deferred.resolve(playbackWav());
    await flushPromises();
    harness.synthCalls[1].deferred.resolve(playbackWav());
    await producer;

    harness.audioInstances[0].currentTime = 2;
    harness.api.seekPlayback(15);
    await flushPromises();
    assert.equal(harness.api.getPlayback().index, 1);
    assert.equal(harness.audioInstances[1].currentTime, 7);

    harness.api.setPlaybackRate(1.5);
    assert.deepEqual(harness.audioInstances.map((audio) => audio.playbackRate), [1.5, 1.5]);

    harness.api.seekPlayback(-10);
    await flushPromises();
    assert.equal(harness.api.getPlayback().index, 0);
    assert.equal(harness.audioInstances[0].currentTime, 7);

    harness.api.seekPlayback(99);
    await flushPromises();
    assert.equal(harness.api.getPlayback().state, "idle");
    assert.equal(harness.api.getPlayback().segments.length, 0);
    assert.deepEqual(harness.revokedUrls, ["blob:test-1", "blob:test-2"]);
  } finally {
    harness.cleanup();
  }
});

test("stale play rejection cannot stop a newer same-epoch seek", async () => {
  const harness = setupPlaybackHarness();
  try {
    const producer = harness.api.startPlayback(Symbol("owner"), "word ".repeat(100), harness.voice);
    harness.synthCalls[0].deferred.resolve(playbackWav());
    await flushPromises();
    harness.synthCalls[1].deferred.resolve(playbackWav());
    await producer;

    harness.audioInstances[1].deferNextPlay = true;
    harness.api.seekPlayback(15);
    await flushPromises();
    assert.equal(harness.api.getPlayback().index, 1);
    assert.equal(harness.playDeferreds.length, 1);

    harness.api.seekPlayback(-15);
    await flushPromises();
    assert.equal(harness.api.getPlayback().index, 0);
    harness.playDeferreds[0].reject(new Error("interrupted"));
    await flushPromises();

    assert.equal(harness.api.getPlayback().state, "playing");
    assert.equal(harness.api.getPlayback().segments.length, 2);
    assert.equal(harness.api.getPlayback().error, null);
  } finally {
    harness.cleanup();
  }
});

test("stale successful play cannot undo wait-at-buffer-end", async () => {
  const harness = setupPlaybackHarness();
  try {
    const producer = harness.api.startPlayback(Symbol("owner"), "word ".repeat(250), harness.voice);
    harness.synthCalls[0].deferred.resolve(playbackWav());
    await flushPromises();
    harness.synthCalls[1].deferred.resolve(playbackWav());
    await flushPromises();
    assert.equal(harness.synthCalls.length, 3);

    harness.audioInstances[1].deferNextPlay = true;
    harness.api.seekPlayback(15);
    await flushPromises();
    assert.equal(harness.api.getPlayback().index, 1);
    harness.api.seekPlayback(99);
    assert.equal(harness.api.getPlayback().audio, null);
    assert.equal(harness.api.getPlayback().state, "loading");

    harness.playDeferreds[0].resolve();
    await flushPromises();
    assert.equal(harness.api.getPlayback().audio, null);
    assert.equal(harness.api.getPlayback().state, "loading");

    harness.synthCalls[2].deferred.resolve(playbackWav());
    await producer;
    assert.equal(harness.api.getPlayback().index, 2);
    assert.equal(harness.audioInstances[2].playCalls, 1);
    assert.equal(harness.api.getPlayback().state, "playing");
  } finally {
    harness.cleanup();
  }
});

test("queue resumes after the first segment outruns background synthesis", async () => {
  const harness = setupPlaybackHarness();
  try {
    const producer = harness.api.startPlayback(Symbol("owner"), "word ".repeat(100), harness.voice);
    harness.synthCalls[0].deferred.resolve(playbackWav());
    await flushPromises();
    harness.audioInstances[0].finish();
    await flushPromises();
    assert.equal(harness.api.getPlayback().state, "loading");
    assert.equal(harness.api.getPlayback().audio, null);

    harness.synthCalls[1].deferred.resolve(playbackWav());
    await producer;
    assert.equal(harness.audioInstances[1].playCalls, 1);
    assert.equal(harness.api.getPlayback().state, "playing");
  } finally {
    harness.cleanup();
  }
});

test("seek past the buffered end waits for background audio without replay", async () => {
  const harness = setupPlaybackHarness();
  try {
    const producer = harness.api.startPlayback(Symbol("owner"), "word ".repeat(100), harness.voice);
    harness.synthCalls[0].deferred.resolve(playbackWav());
    await flushPromises();
    harness.api.seekPlayback(99);
    assert.equal(harness.api.getPlayback().state, "loading");
    assert.equal(harness.api.getPlayback().audio, null);
    assert.equal(harness.audioInstances[0].playCalls, 1);

    harness.synthCalls[1].deferred.resolve(playbackWav());
    await producer;
    assert.equal(harness.audioInstances[0].playCalls, 1);
    assert.equal(harness.audioInstances[1].playCalls, 1);
  } finally {
    harness.cleanup();
  }
});

test("background arrival cannot override a rewind started during a gap", async () => {
  const harness = setupPlaybackHarness();
  try {
    const producer = harness.api.startPlayback(Symbol("owner"), "word ".repeat(100), harness.voice);
    harness.synthCalls[0].deferred.resolve(playbackWav());
    await flushPromises();
    harness.audioInstances[0].finish();
    await flushPromises();

    harness.audioInstances[0].deferNextPlay = true;
    harness.api.seekPlayback(-5);
    await flushPromises();
    assert.equal(harness.api.getPlayback().audio, harness.audioInstances[0]);
    assert.equal(harness.playDeferreds.length, 1);

    harness.synthCalls[1].deferred.resolve(playbackWav());
    await producer;
    assert.equal(harness.api.getPlayback().index, 0);
    assert.equal(harness.audioInstances[1].playCalls, 0);

    harness.playDeferreds[0].resolve();
    await flushPromises();
    assert.equal(harness.api.getPlayback().state, "playing");
    assert.equal(harness.api.getPlayback().index, 0);
  } finally {
    harness.cleanup();
  }
});

test("stop aborts background synthesis and releases every prepared segment", async () => {
  const harness = setupPlaybackHarness();
  try {
    const producer = harness.api.startPlayback(Symbol("owner"), "word ".repeat(100), harness.voice);
    const signal = harness.synthCalls[0].signal;
    harness.synthCalls[0].deferred.resolve(playbackWav());
    await flushPromises();
    assert.equal(harness.synthCalls.length, 2);

    harness.api.stopPlayback();
    assert.equal(signal.aborted, true);
    assert.deepEqual(harness.revokedUrls, ["blob:test-1"]);
    assert.equal(harness.audioInstances[0].src, "");

    harness.synthCalls[1].deferred.resolve(playbackWav());
    await producer;
    assert.equal(harness.createdUrls.length, 1);
  } finally {
    harness.cleanup();
  }
});

test("stale synthesis result cannot restart playback", async () => {
  const harness = setupPlaybackHarness();
  try {
    const producer = harness.api.startPlayback(Symbol("owner"), "word ".repeat(100), harness.voice);
    const firstDeferred = harness.synthCalls[0].deferred;
    harness.api.stopPlayback();
    firstDeferred.resolve(playbackWav());
    await producer;
    assert.equal(harness.createdUrls.length, 0);
    assert.equal(harness.audioInstances.length, 0);
    assert.equal(harness.api.getPlayback().state, "idle");
  } finally {
    harness.cleanup();
  }
});

test("malformed WAV and format mismatch fail safely in inspection", () => {
  const first = pcmWav(Uint8Array.of(1, 2, 3, 4), 44_100);
  const second = pcmWav(Uint8Array.of(5, 6, 7, 8), 48_000);
  const format = inspectMonoPcmWav(first).format;
  assert.throws(() => inspectMonoPcmWav(second, format), /WAV formats do not match/);
  assert.throws(() => inspectMonoPcmWav(new Uint8Array([1, 2, 3, 4])), /invalid WAV chunk/);
});

test("background WAV format failure stops current playback with one error", async () => {
  const harness = setupPlaybackHarness();
  try {
    const producer = harness.api.startPlayback(Symbol("owner"), "word ".repeat(100), harness.voice);
    harness.synthCalls[0].deferred.resolve(playbackWav(10));
    await flushPromises();
    harness.synthCalls[1].deferred.resolve(playbackWav(12));
    await producer;

    const playback = harness.api.getPlayback();
    assert.equal(playback.state, "idle");
    assert.match(playback.error, /WAV formats do not match/);
    assert.deepEqual(harness.revokedUrls, ["blob:test-1"]);
  } finally {
    harness.cleanup();
  }
});

test("background synthesis failure allows active buffered segment to finish playing", async () => {
  const harness = setupPlaybackHarness();
  try {
    const producer = harness.api.startPlayback(Symbol("owner"), "word ".repeat(100), harness.voice);
    harness.synthCalls[0].deferred.resolve(playbackWav(10));
    await flushPromises();
    assert.equal(harness.api.getPlayback().state, "playing");
    assert.equal(harness.synthCalls.length, 2);

    // Chunk 1 fails with network error
    harness.synthCalls[1].deferred.reject(new Error("Network drop"));
    await producer;

    // Segment 0 is still playing; audio is not aborted mid-sentence
    assert.equal(harness.api.getPlayback().state, "playing");
    assert.equal(harness.api.getPlayback().segments.length, 1);
    assert.equal(harness.api.getPlayback().producerDone, true);
    assert.equal(harness.api.getPlayback().pendingError, "Network drop");

    // When segment 0 finishes, playback stops and surfaces the pending error
    harness.audioInstances[0].finish();
    await flushPromises();
    assert.equal(harness.api.getPlayback().state, "idle");
    assert.equal(harness.api.getPlayback().error, "Network drop");
  } finally {
    harness.cleanup();
  }
});

test("progressive playback allows cumulative audio across chunks to exceed 16 MiB", async () => {
  const harness = setupPlaybackHarness();
  try {
    const producer = harness.api.startPlayback(Symbol("owner"), "word ".repeat(350), harness.voice);
    // Each simulated chunk is ~5 MB
    const largeWav = (rate) => ({
      audioBase64: Buffer.from(pcmWav(new Uint8Array(5 * 1024 * 1024), rate)).toString("base64"),
      mimeType: "audio/wav",
    });

    for (let i = 0; i < 4; i++) {
      assert.equal(harness.synthCalls.length, i + 1);
      harness.synthCalls[i].deferred.resolve(largeWav(100));
      await flushPromises();
    }
    await producer;

    // 4 chunks * 5 MiB = 20 MiB (> 16 MiB), should not throw 'Speech audio is too large'
    const playback = harness.api.getPlayback();
    assert.equal(playback.segments.length, 4);
    assert.ok(playback.bufferedBytes > 16 * 1024 * 1024);
    assert.equal(playback.error, null);
  } finally {
    harness.cleanup();
  }
});
