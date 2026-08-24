import assert from "node:assert/strict";
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

test("cleanMarkdown is exposed for tests", () => {
  assert.equal(typeof cleanMarkdown, "function");
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

test("handles code blocks by replacing fenced blocks and cleaning inline code", () => {
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
    "Here is an example: . End of example.",
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

test("fenced code becomes a language-neutral pause", () => {
  assert.equal(cleanMarkdown("Before\n```js\nconst x = 1\n```\nAfter"), "Before . After");
});
