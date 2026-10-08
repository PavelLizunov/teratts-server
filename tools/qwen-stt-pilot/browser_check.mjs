// Local/private page verification only; use installed Playwright and private browser HOME.
import fs from 'node:fs';
const [playwrightPath, executablePath, url, receiptPath] = process.argv.slice(2);
if (!receiptPath) throw new Error('Expected Playwright module, browser binary, URL and receipt path');
const { chromium } = await import(playwrightPath);
const browser = await chromium.launch({ executablePath, headless: true,
  args: ['--no-sandbox', '--proxy-server=direct://'],
  env: { PATH: process.env.PATH, HOME: process.env.HOME,
         XDG_CONFIG_HOME: process.env.HOME, XDG_CACHE_HOME: process.env.HOME } });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  const response = await page.goto(url, { waitUntil: 'domcontentloaded' });
  if (response.status() !== 200) throw new Error('Page HTTP failure');
  if (await page.locator('audio').count() !== 5) throw new Error('Wrong speech clip count');
  const audio = page.locator('audio').first();
  await audio.evaluate(async element => {
    element.preload = 'auto'; element.load();
    await new Promise((resolve, reject) => {
      element.onloadedmetadata = resolve;
      element.onerror = () => reject(Error('Embedded audio decode failed'));
    });
  });
  const duration = await audio.evaluate(element => element.duration);
  if (Math.abs(duration - 13.2260625) > .01) throw new Error('Wrong original audio');
  await audio.evaluate(element => element.play());
  await page.getByRole('button', { name: 'Этот вариант ближе' }).first().click();
  if (await audio.evaluate(element => element.paused)) throw new Error('Vote interrupted playback');
  await page.locator('.review summary').first().click();
  await page.locator('textarea').first().fill('Проверка исправления без отправки');
  const review = await page.evaluate(() => JSON.parse(localStorage.getItem(Object.keys(localStorage)[0])));
  if (!Object.values(review).some(value => value.reference === 'Проверка исправления без отправки'))
    throw new Error('Reference not retained');
  const downloadPromise = page.waitForEvent('download');
  await page.locator('#export').click();
  const download = await downloadPromise;
  if (download.suggestedFilename() !== 'stt-my-review.json') throw new Error('Wrong export');
  const text = fs.readFileSync(await download.path(), 'utf8');
  if (!JSON.parse(text).manifest_sha256) throw new Error('Export missing provenance');
  await page.locator('#clip-type').selectOption('control');
  if (await page.locator('audio').count() !== 2) throw new Error('Wrong control count');
  await page.setViewportSize({ width: 390, height: 844 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  if (overflow || errors.length) throw new Error('Browser integrity failed: ' + errors.join(';'));
  const receipt = { http: 200, speech: 5, controls: 2, audio_duration: duration,
                    vote_preserves_audio: true, reference_retained: true, export_verified: true,
                    mobile_overflow: false, page_errors: errors, checked_at: new Date().toISOString() };
  fs.writeFileSync(receiptPath, JSON.stringify(receipt, null, 2));
  console.log(JSON.stringify(receipt));
} finally { await browser.close(); }
