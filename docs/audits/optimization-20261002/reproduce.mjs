import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { PlaybackCoordinator } from '../../../dsh-plugin/lib/coordinator.js';
import { splitSpeechText } from '../../../dsh-plugin/lib/speech-text.js';
import { isolatedService } from '../../../dsh-plugin/test/helpers/runtime.js';

// Diagnostic assertions describe current behavior, not desired regression behavior.
test('rejected metadata refresh does not re-date stale revision (candidate dismissed)', async (t) => {
  const coordinator = new PlaybackCoordinator();
  t.after(() => coordinator.dispose());
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => {
    calls++;
    return calls === 1
      ? { ok: true, json: async () => ({ synthesis_revision: 'old-revision' }) }
      : { ok: false, status: 503 };
  });
  const endpoint = 'http://127.0.0.1:8088';
  assert.equal(await coordinator.getOrFetchSynthesisRevision(endpoint), 'old-revision');
  coordinator.cachedRevisionTimestamp = 0;
  assert.equal(await coordinator.getOrFetchSynthesisRevision(endpoint), null);
  assert.equal(coordinator.cachedRevisionTimestamp, 0);
  assert.equal(await coordinator.getOrFetchSynthesisRevision(endpoint), null);
  assert.equal(calls, 3);
});

test('browser adapter unwraps rejected lease values correctly (candidate dismissed)', async () => {
  const source = await readFile(new URL('../../../dsh-plugin/lib/client.js', import.meta.url), 'utf8');
  const context = vm.createContext({ window: { __ModuleLoader__: { load() {} } }, console,
    AbortController, setTimeout, clearTimeout, setInterval, clearInterval,
    TextDecoder, Uint8Array, DataView, Math, Number });
  vm.runInContext(source, context);
  const coordinator = new PlaybackCoordinator();
  try {
    context.response = { ok: true, value: coordinator.renewForeground('expired-tab', 1) };
    const value = vm.runInContext('unwrapRemoteResult(response)', context);
    assert.equal(value.ok, false, 'apply wraps lease calls, so heartbeat sees actual rejection');
  } finally { coordinator.dispose(); }
});

test('first server preparation result is keyed by old revision and repeated unnecessarily', async (t) => {
  const { service } = await isolatedService(t, { prepareMode: 'on' });
  let calls = 0;
  t.mock.method(service, 'prepareConfigured', async () => {
    calls++;
    return { text: 'ready', preparationRevision: 'p1', warnings: [] };
  });
  const first = await service.prepareText('raw', 'message');
  assert.equal(first.text, 'ready');
  assert.equal(calls, 1);
  await service.prepareText('raw', 'message');
  assert.equal(calls, 2, 'second identical request cannot reuse first entry after revision discovery');
  await service.prepareText('raw', 'message');
  assert.equal(calls, 2, 'third request reuses the correctly keyed entry');
});

test('custom second chunk limit is not validated with other limits', () => {
  assert.doesNotThrow(() => splitSpeechText('a '.repeat(40), {
    firstChars: 20, secondChars: -1, nextChars: 30,
  }));
});
