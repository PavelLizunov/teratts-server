import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { performance } from 'node:perf_hooks';

const [rootArg = '.', mode = 'check', workload = 'search-v1'] = process.argv.slice(2);
const root = resolve(rootArg);
const fixture = await readFile(new URL('../../dsh-plugin/test/fixtures/technical-markdown.md', import.meta.url), 'utf8');
const corpus = {
  'search-v1': [fixture, '['.repeat(12000), '!['.repeat(5000), '[a](x(y)) ![b](z) `identifier` <ru>Привет.</ru>'],
  'full-v1': [fixture.repeat(3), '['.repeat(18000), '!['.repeat(6000), '[Вложенная ссылка](https://example.test/a(b))\n![Картинка](image.png)'],
  quality: ['[label]`(`url)', '![image]`(`url)', '[x](a(b)c)', '[](x)', '![](x)', '[[]](x)', '[outer [inner](x)', '[a](unclosed', '`[x](y)`', '<en>Hello.</en> **Жирный** _текст_', '| a | [b](c) |\n|---|---|', '```js\n[a](b);\n```'],
};
// Fixed, deterministic fuzz cases; not user data or mutable random state.
let seed = 0x91acd;
const atoms = ['[', ']', '(', ')', '!', '`', 'a', ' ', '<ru>', '</ru>', '\n', '*'];
for (let i = 0; i < 64; i++) {
  let text = '';
  for (let j = 0; j < 80; j++) {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    text += atoms[seed % atoms.length];
  }
  corpus.quality.push(text);
}
assert.ok(workload in corpus, 'unknown workload');
const host = await import(pathToFileURL(resolve(root, 'dsh-plugin/lib/speech-text.js')));
globalThis.window = { __ModuleLoader__: { load() {} } };
globalThis.document = { querySelector: () => null, createElement: () => ({ dataset: {} }), head: { appendChild() {} } };
await import(pathToFileURL(resolve(root, 'dsh-plugin/lib/client.js')));
const client = { cleanMarkdown: globalThis.__teratts_cleanMarkdown, splitSpeechText: globalThis.__teratts_splitSpeechText };
const digest = (value) => createHash('sha256').update(JSON.stringify(value)).digest('hex');
function output(api, text, mutant) {
  const cleaned = mutant === 'empty' ? '' : api.cleanMarkdown(text);
  const chunks = api.splitSpeechText(cleaned);
  if (mutant === 'corrupt') chunks.push('unwanted spoken content');
  return { cleaned, chunks };
}
const referenceURL = new URL('./reference.json', import.meta.url);
if (mode === 'reference') {
  const expected = Object.fromEntries(Object.entries(corpus).map(([key, texts]) => [key, texts.map(text => digest(output(host, text)))]));
  await writeFile(referenceURL, JSON.stringify(expected, null, 2) + '\n', { flag: 'wx' });
} else {
  const reference = JSON.parse(await readFile(referenceURL, 'utf8'));
  function check(mutant) {
    for (const name of ['quality', workload]) {
      corpus[name].forEach((text, i) => {
        assert.equal(digest(output(host, text, mutant)), reference[name][i], `Host ${name}:${i}`);
        assert.equal(digest(output(client, text, mutant)), reference[name][i], `client ${name}:${i}`);
      });
    }
  }
  check();
  // Actual production pipeline outputs are fault-injected into the same checker.
  assert.throws(() => check('empty'), assert.AssertionError);
  assert.throws(() => check('corrupt'), assert.AssertionError);
  const result = { quality: true, negative_controls: { empty_output: true, corrupted_chunks: true }, workload };
  if (mode === 'bench') {
    const run = () => {
      let count = 0;
      for (const text of corpus[workload]) count += output(host, text).chunks.length;
      return count;
    };
    run(); run();
    const start = performance.now();
    result.checksum = run();
    result.seconds = (performance.now() - start) / 1000;
    result.peak_rss_bytes = process.resourceUsage().maxRSS * 1024;
  } else assert.equal(mode, 'check');
  console.log(JSON.stringify(result));
}
