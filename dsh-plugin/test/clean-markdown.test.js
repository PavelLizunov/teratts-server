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
const mergeMonoPcmWavs = globalThis.__teratts_mergeMonoPcmWavs;
const technicalMarkdown = await readFile(
  new URL("./fixtures/technical-markdown.md", import.meta.url),
  "utf8",
);

test("client helpers are exposed for tests", () => {
  assert.equal(typeof cleanMarkdown, "function");
  assert.equal(typeof nextPlaybackRate, "function");
  assert.equal(typeof clampSeekTime, "function");
  assert.equal(typeof splitSpeechText, "function");
  assert.equal(typeof mergeMonoPcmWavs, "function");
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

test("preserves comparison expressions that are not HTML tags", () => {
  assert.equal(cleanMarkdown("3 < 5 and 5 > 2"), "3 < 5 and 5 > 2");
  assert.equal(cleanMarkdown("x < y && z > 0"), "x < y && z > 0");
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

test("technical spec splits at speech boundaries without losing text", () => {
  const cleaned = cleanMarkdown(technicalMarkdown);
  const chunks = splitSpeechText(cleaned);
  assert.deepEqual(
    chunks.map((chunk) => chunk.length),
    [773, 783, 589],
  );
  assert.ok(chunks.every((chunk) => chunk.length <= 800));
  assert.equal(chunks.join(" "), cleaned);
  const tagged = `<ru>${"слово ".repeat(200).trim()}</ru>`;
  assert.deepEqual(splitSpeechText(tagged), [tagged]);
  assert.throws(() => splitSpeechText(cleaned, 0), /invalid speech chunk size/);
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

test("merges mono PCM WAV chunks into one bounded WAV", () => {
  const first = pcmWav(Uint8Array.of(1, 2, 3, 4));
  const second = pcmWav(Uint8Array.of(5, 6));
  const merged = mergeMonoPcmWavs([first, second]);
  const header = new DataView(merged.buffer);
  assert.equal(merged.length, 50);
  assert.equal(header.getUint32(4, true), 42);
  assert.equal(header.getUint32(40, true), 6);
  assert.deepEqual([...merged.subarray(44)], [1, 2, 3, 4, 5, 6]);
  assert.throws(() => mergeMonoPcmWavs([first, pcmWav(Uint8Array.of(7, 8), 48_000)]));
  assert.throws(() => mergeMonoPcmWavs([first, second], 49), /too large/);
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
  assert.match(fnStr, /clampSeekTime/);
  assert.match(fnStr, /nextPlaybackRate/);
  assert.match(fnStr, /e\.stopPropagation\(\)/);
  assert.match(fnStr, /Request timed out/);
});
