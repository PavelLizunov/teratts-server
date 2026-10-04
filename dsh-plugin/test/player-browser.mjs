// Opt-in real-browser regression; reuse installed tools without new dependencies.
// DSH_TEST_NODE_MODULES=<runtime modules> DSH_PLAYWRIGHT_MODULE=<index.mjs> node this-file
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const runtime = process.env.DSH_TEST_NODE_MODULES;
if (!runtime || !process.env.DSH_PLAYWRIGHT_MODULE) throw new Error("Set DSH_TEST_NODE_MODULES and DSH_PLAYWRIGHT_MODULE");
const { chromium } = await import(pathToFileURL(process.env.DSH_PLAYWRIGHT_MODULE).href);
const source = await readFile(process.env.DSH_PLAYER_CLIENT_FILE || new URL("../lib/client.js", import.meta.url), "utf8");
const react = await readFile(`${runtime}/react/umd/react.production.min.js`, "utf8");
const reactDom = await readFile(`${runtime}/react-dom/umd/react-dom.production.min.js`, "utf8");
const fixture = `
    const { createRoot } = ReactDOM;
    window.__ModuleLoader__ = { load(entry) { window.plugin = entry.factory(name => name === 'react' ? React : ReactDOM); } };
    window.mountFixture = async () => {
      class FakeAudio {
        currentTime = 0; volume = 1; playbackRate = 1;
        play() { return Promise.resolve(); } pause() {} removeAttribute() {} load() {}
      }
      window.Audio = FakeAudio;
      const bytes = new Uint8Array(44 + 8000 * 2 * 60);
      const view = new DataView(bytes.buffer);
      const tag = (offset, value) => [...value].forEach((letter, i) => bytes[offset + i] = letter.charCodeAt(0));
      tag(0, 'RIFF'); view.setUint32(4, bytes.length - 8, true); tag(8, 'WAVE'); tag(12, 'fmt ');
      view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
      view.setUint32(24, 8000, true); view.setUint32(28, 16000, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
      tag(36, 'data'); view.setUint32(40, bytes.length - 44, true);
      let binary = ''; for (const byte of bytes) binary += String.fromCharCode(byte);
      const voice = {
        synthesize: async () => ({ ok: true, value: { audioBase64: btoa(binary), mimeType: 'audio/wav' } }),
        acquireForeground: async () => ({ ok: true, value: { ok: true } }),
        renewForeground: async () => ({ ok: true, value: { ok: true } }),
        releaseForeground: async () => ({ ok: true, value: { ok: true } }),
        recordTelemetry: async () => ({ ok: true, value: {} }),
        prepare: async text => ({ ok: true, value: { text } }),
      };
      voice.synthesizeObserved = voice.synthesize;
      let renderAction;
      window.disposePlugin = await plugin.apply({ remote: { $mount: async () => {} }, get: () => voice,
        slots: { inject: (_name, callback) => callback(), register: (descriptor, render) => { if (descriptor.name === 'conversation.chat.assistant-actions') renderAction = render; return () => {}; } } });
      const props = { messageId: 'm1', useChat: (select) => select({ nodes: [{ kind: 'assistant', messageId: 'm1', content: [{ type: 'text', text: 'Test speech.' }] }] }),
        useSession: (select) => select({ status: 'idle' }) };
      const root = createRoot(document.getElementById('actions'));
      root.render(renderAction(props)); window.unmountFixture = () => root.unmount();
    };
  `;
const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"],
  ...(process.env.DSH_CHROMIUM_EXECUTABLE ? { executablePath: process.env.DSH_CHROMIUM_EXECUTABLE } : {}) });
try {
  for (const width of [1280, 390, 320]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.setContent(`<style>
      body{margin:0;background:#eee;font-family:sans-serif} [data-conversation-session]{height:2000px}
      .message{padding:20px;transform:translateZ(0);contain:layout paint}
      #actions{opacity:0;display:flex} .message:hover #actions,.message:focus-within #actions{opacity:1}
      [data-conversation-composer-seat]{position:fixed;bottom:0;left:0;right:0;height:100px;background:#ccc}
      #other{margin-top:180px} :root{--dsw-alias-label-primary:#222;--dsw-specific-menu:#fff}
    </style><div data-conversation-session><div class="message"><div id="actions"></div></div>
      <button id="other">Another message</button><div data-conversation-composer-seat><textarea></textarea></div></div>`);
    await page.addScriptTag({ content: react });
    await page.addScriptTag({ content: reactDom });
    await page.addScriptTag({ content: fixture });
    await page.addScriptTag({ content: source });
    await page.evaluate(() => window.mountFixture());
    await page.locator(".message").hover();
    await page.locator('.teratts-action').waitFor({ state: 'attached', timeout: 5000 }).catch(async error => {
      console.error('Fixture rendering:', errors, await page.locator('#actions').innerHTML()); throw error;
    });
    await page.locator('.teratts-action').click();
    const player = page.getByRole("region", { name: "Speech player" });
    await player.waitFor({ timeout: 5000 }).catch(async error => {
      console.error('Playback fixture:', errors, await page.locator('#actions').innerText()); throw error;
    });
    await page.getByRole("button", { name: "Pause speech", exact: true }).waitFor();
    await page.locator("#other").click();
    await page.mouse.move(width - 1, 450);
    await page.waitForFunction(() => getComputedStyle(document.querySelector('.teratts-player')).animationName === 'teratts-pop-in');
    // Remove entry animation for exact geometry assertions, not positioning CSS.
    await player.evaluate(el => el.style.animation = 'none');
    const original = await player.boundingBox();
    assert.ok(Math.abs(original.x + original.width / 2 - width / 2) < 1, `center at ${width}px`);
    assert.ok(original.x >= 12 && original.x + original.width <= width - 12, `viewport gutters at ${width}px`);
    assert.ok(original.y + original.height <= 788, `composer clearance at ${width}px`);
    assert.equal(await player.evaluate(el => el.parentElement === document.body), true);
    assert.equal(await page.locator('#actions').evaluate(el => getComputedStyle(el).opacity), '0');
    assert.equal(await player.evaluate(el => getComputedStyle(el).opacity), '1');
    await page.evaluate(() => window.scrollTo(0, 600));
    assert.deepEqual(await player.boundingBox(), original, `scroll stability at ${width}px`);
    await page.getByRole('button', { name: 'Pause speech', exact: true }).click();
    await page.getByRole('button', { name: 'Resume speech', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Resume speech', exact: true }).click();
    const rateButton = player.locator('.teratts-pill-btn').filter({ hasText: '×' });
    const oldRate = await rateButton.innerText();
    await rateButton.click();
    assert.notEqual(await rateButton.innerText(), oldRate);
    await page.getByRole('slider', { name: 'Seek' }).fill('20');
    await page.evaluate(() => document.querySelector('[data-conversation-composer-seat]').style.height = '180px');
    await page.waitForFunction(() => document.querySelector('.teratts-player').style.getPropertyValue('--teratts-composer-offset') === '192px');
    assert.ok((await player.boundingBox()).y + (await player.boundingBox()).height <= 708);
    await page.getByRole('button', { name: 'Stop speech' }).click();
    await player.waitFor({ state: 'detached' });
    await page.evaluate(() => { window.scrollTo(0, 0); document.querySelector('[data-conversation-composer-seat]').style.height = '100px'; });
    await page.locator('.message').hover();
    await page.locator('.teratts-action').click();
    await player.waitFor();
    await page.evaluate(() => window.unmountFixture());
    await player.waitFor({ state: 'detached' });
    assert.deepEqual(errors, []);
    await page.evaluate(() => { window.unmountFixture(); window.disposePlugin(); });
    await page.close();
    console.log(`PASS desktop/mobile player geometry, hover, click, scroll, resize, pause, seek, rate, stop: ${width}px`);
  }
} finally { await browser.close(); }
