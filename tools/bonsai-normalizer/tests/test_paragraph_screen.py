"""Model/socket-free checks for the once-only frozen paragraph collector."""
import base64
import datetime
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bonsai_paragraph_screen as screen
from bonsai_paragraph_structurer import render_paragraphs

SOURCE = 'Первая задача готова. Вторая задача готова. Третья задача готова. Четвёртая задача готова.'
NOW = 1800000000.0
DECK = {'gateway_sha256': screen.GATEWAY_SHA256, 'services': ['active'] * 4}


def admission():
    return {'at': datetime.datetime.fromtimestamp(NOW, datetime.timezone.utc).isoformat(),
            'source_commit': screen.SOURCE_COMMIT, 'source_service_sha256': screen.SERVICE_SHA256,
            'copied_service_sha256': screen.SERVICE_SHA256, 'health': dict(screen.HEALTH),
            'vision_lock_free': True, 'memory': {'available_GiB': 6, 'swap_GiB': 8}}


class Transport:
    def __init__(self, *, content='{"break_after":[1]}', fault=None, mutate=None,
                 raw=None, on_call=None, unload_fault=False):
        self.content, self.fault, self.mutate = content, fault, mutate
        self.raw, self.on_call, self.unload_fault = raw, on_call, unload_fault
        self.paths, self.payloads, self.timeouts = [], [], []

    def open(self, request, timeout):
        path = request.full_url.removeprefix(screen.BASE)
        self.paths.append(path)
        if path == '/health':
            return io.BytesIO(json.dumps(screen.HEALTH).encode())
        if path == '/unload':
            if self.unload_fault:
                raise OSError('synthetic settlement failure')
            return io.BytesIO(b'{"unloaded":true}')
        if path != '/v1/chat/completions':
            raise AssertionError(path)
        self.payloads.append(json.loads(request.data))
        self.timeouts.append(timeout)
        if self.on_call:
            self.on_call()
        if self.fault:
            raise self.fault
        data = {'model': screen.DEFAULT_MODEL, 'choices': [{'finish_reason': 'stop',
                'message': {'content': self.content}}], 'bonsai': {
                'revision': screen.DEFAULT_REVISION, 'thinking': False, 'profile': 'baseline',
                'memory_end': {'available_GiB': 3, 'swap_GiB': 8}}}
        if self.mutate:
            self.mutate(data)
        return io.BytesIO(self.raw if self.raw is not None else json.dumps(data).encode())


class TestParagraphScreen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inputs, self.output = self.root / 'inputs.json', self.root / 'results.json'
        cells = [{'id': name, 'source': SOURCE, 'break_after': [1],
                  'expected': render_paragraphs(SOURCE, '{"break_after":[1]}'), 'status': 'applied'}
                 for name in screen.CELL_IDS]
        self.inputs.write_text(json.dumps({'cells': cells}), encoding='utf-8')
        self.inputs_hash = screen.digest(self.inputs.read_bytes())
        frozen = patch.object(screen, 'INPUTS_SHA256', self.inputs_hash)
        frozen.start()
        self.addCleanup(frozen.stop)
        self.connect = patch.object(socket.socket, 'connect', side_effect=AssertionError('real socket reached'))
        self.connect.start()
        self.addCleanup(self.connect.stop)

    def run_screen(self, transport, **kwargs):
        return screen.collect(self.inputs, self.inputs_hash, self.output, 'synthetic-token-' * 3,
            kwargs.pop('observation', admission()), opener=transport, wall_clock=lambda: NOW,
            deck_observer=kwargs.pop('deck_observer', lambda: DECK), **kwargs)

    def result(self):
        return json.loads(self.output.read_text())

    def test_four_calls_real_client_exact_plan_and_once_only(self):
        t = Transport()
        result = self.run_screen(t)
        self.assertTrue(result['completed'] and result['http_settled'] and result['deck_preserved'])
        self.assertFalse(result['unknown_outcome'])
        self.assertEqual(result['model_calls'], 4)
        self.assertTrue(all(r['useful_grouping'] and r['insertion_plan_verified'] for r in result['rows']))
        self.assertTrue(all('response_format' not in p for p in t.payloads))
        self.assertEqual(t.paths[-2:], ['/unload', '/health'])
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        before = list(t.paths)
        with self.assertRaises(FileExistsError):
            self.run_screen(t)
        self.assertEqual(t.paths, before)
        self.assertEqual(result, self.result())
        self.assertIn('required separately', result['Mac_final_lock_verification'])

    def test_private_fsynced_intent_exists_before_transport(self):
        def check():
            receipt = self.result()
            self.assertTrue(receipt['unknown_outcome'])
            self.assertEqual(receipt['model_calls'], len(t.payloads))
            self.assertEqual(receipt['rows'][-1]['outcome'], 'submitted_unknown')
        t = Transport(on_call=check)
        with patch.object(screen.os, 'fsync', wraps=screen.os.fsync) as fsync:
            self.run_screen(t)
        self.assertGreaterEqual(fsync.call_count, 9)
        self.assertNotIn('synthetic-token-', self.output.read_text())

    def test_selection_rejections_stay_in_denominator_without_repair(self):
        t = Transport(content='```json\n{"break_after":[1]}\n```')
        result = self.run_screen(t)
        self.assertTrue(result['completed'])
        self.assertEqual(result['model_calls'], 4)
        self.assertTrue(all(not r['strict_selection_valid'] and not r['useful_grouping']
                            and r['returned'] == SOURCE for r in result['rows']))
        self.assertTrue(all(r['metadata']['reason'] == 'invalid_edit_selection' for r in result['rows']))

    def test_empty_selection_is_unchanged_not_useful_when_split_expected(self):
        result = self.run_screen(Transport(content='{"break_after":[]}'))
        self.assertTrue(result['completed'])
        self.assertTrue(all(r['metadata']['status'] == 'unchanged' and not r['useful_grouping']
                            for r in result['rows']))

    def test_received_http_errors_are_known_preserve_bytes_and_stop(self):
        for code in [400, 503]:
            with self.subTest(code=code):
                self.output = self.root / f'error-{code}.json'
                raw = b'{"error":"known rejection"}'
                error = urllib.error.HTTPError(screen.BASE + '/v1/chat/completions', code,
                                                'test', {}, io.BytesIO(raw))
                t = Transport(fault=error)
                with self.assertRaisesRegex(ValueError, 'HTTP rejection'):
                    self.run_screen(t)
                r = self.result()
                self.assertFalse(r['unknown_outcome'] or r['completed'])
                self.assertEqual(r['model_calls'], 1)
                self.assertEqual(r['rows'][0]['http_status'], code)
                self.assertEqual(base64.b64decode(r['rows'][0]['raw_base64']), raw)
                self.assertTrue(r['http_settled'])

    def test_unknown_transport_timeout_stops_without_unload_or_replay(self):
        t = Transport(fault=TimeoutError('synthetic unknown'))
        with self.assertRaisesRegex(RuntimeError, 'Unresolved'):
            self.run_screen(t)
        r = self.result()
        self.assertTrue(r['unknown_outcome'])
        self.assertEqual(r['model_calls'], 1)
        self.assertNotIn('/unload', t.paths)
        with self.assertRaises(FileExistsError):
            self.run_screen(t)
        self.assertEqual(len(t.payloads), 1)

    def test_body_read_timeout_stays_unknown(self):
        class SlowBody(io.BytesIO):
            def read(self, *_):
                raise TimeoutError('read outcome unknown')
        t = Transport()
        old = t.open
        def open_response(request, timeout):
            if request.full_url.endswith('/v1/chat/completions'):
                t.paths.append('/v1/chat/completions')
                return SlowBody()
            return old(request, timeout)
        t.open = open_response
        with self.assertRaises(RuntimeError):
            self.run_screen(t)
        self.assertTrue(self.result()['unknown_outcome'])
        self.assertNotIn('/unload', t.paths)

    def test_known_malformed_and_oversized_bodies_stop_and_settle(self):
        for label, raw in [('invalid-json', b'not-json'), ('oversized', b'x' * 65537),
                           ('invalid-utf8', b'\xff')]:
            with self.subTest(label=label):
                self.output = self.root / (label + '.json')
                t = Transport(raw=raw)
                with self.assertRaises((ValueError, UnicodeError)):
                    self.run_screen(t)
                r = self.result()
                self.assertFalse(r['unknown_outcome'])
                self.assertEqual(r['model_calls'], 1)
                self.assertEqual(base64.b64decode(r['rows'][0]['raw_base64']), raw)
                self.assertTrue(r['http_settled'])

    def test_identity_profile_finish_and_resources_stop(self):
        mutations = [lambda d: d.update(model='wrong'),
            lambda d: d['bonsai'].update(revision='wrong'),
            lambda d: d['bonsai'].update(thinking=True),
            lambda d: d['bonsai'].update(profile='mtp'),
            lambda d: d['choices'][0].update(finish_reason='length'),
            lambda d: d['bonsai']['memory_end'].update(available_GiB=1.9),
            lambda d: d['bonsai']['memory_end'].update(swap_GiB=8.251),
            lambda d: d['bonsai']['memory_end'].update(available_GiB=float('nan')),
            lambda d: d['bonsai']['memory_end'].update(swap_GiB='8')]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                self.output = self.root / f'drift-{index}.json'
                t = Transport(mutate=mutate)
                # Nonfinite JSON cannot be saved as parsed data; raw survives.
                with self.assertRaises((ValueError, MemoryError)):
                    self.run_screen(t)
                r = self.result()
                self.assertEqual(r['model_calls'], 1)
                self.assertFalse(r['unknown_outcome'])

    def test_exponent_overflow_is_known_raw_preserved_and_settled(self):
        for location in ('resource', 'unrelated'):
            with self.subTest(location=location):
                self.output = self.root / f'overflow-{location}.json'
                def mutate(data):
                    if location == 'resource':
                        data['bonsai']['memory_end']['available_GiB'] = 'OVERFLOW'
                    else:
                        data['extra'] = 'OVERFLOW'
                template = Transport(mutate=mutate)
                request = screen.urllib.request.Request(screen.BASE + '/v1/chat/completions', data=b'{}')
                raw = template.open(request, 1).read().replace(b'"OVERFLOW"', b'1e999')
                t = Transport(raw=raw)
                with self.assertRaisesRegex(ValueError, 'Nonfinite JSON response'):
                    self.run_screen(t)
                r = self.result()
                self.assertEqual(r['model_calls'], 1)
                self.assertFalse(r['unknown_outcome'] or r['completed'])
                self.assertEqual(base64.b64decode(r['rows'][0]['raw_base64']), raw)
                self.assertNotIn('response', r['rows'][0])
                self.assertTrue(r['http_settled'] and r['deck_preserved'])
                self.assertEqual(t.paths, ['/health', '/v1/chat/completions', '/unload', '/health'])

    def test_save_failure_does_not_skip_known_settlement_or_hide_primary_error(self):
        dumps = screen.json.dumps
        for failure in ('primary-bookkeeping', 'before-settlement', 'both-settlement-saves'):
            with self.subTest(failure=failure):
                self.output = self.root / f'save-{failure}.json'
                t = Transport(raw=b'not-json' if failure != 'primary-bookkeeping' else None)
                def fail_save(data, *args, **kwargs):
                    if isinstance(data, dict) and 'collector_sha256' in data:
                        rows = data['rows']
                        primary = (failure == 'primary-bookkeeping' and rows
                                   and 'returned' in rows[0] and 'stopped_error_type' not in data)
                        settlement = ('screen_elapsed_seconds' in data
                                      and (failure == 'both-settlement-saves'
                                           or (failure == 'before-settlement'
                                               and 'total_collection_seconds' not in data)))
                        if primary or settlement:
                            raise OSError('synthetic receipt save failure')
                    return dumps(data, *args, **kwargs)
                expected = OSError if failure == 'primary-bookkeeping' else json.JSONDecodeError
                with patch.object(screen.json, 'dumps', side_effect=fail_save):
                    with self.assertRaises(expected):
                        self.run_screen(t)
                self.assertEqual(t.paths, ['/health', '/v1/chat/completions', '/unload', '/health'])
                r = self.result()
                self.assertFalse(r['unknown_outcome'])
                self.assertEqual(r['rows'][0]['outcome'], 'response_received')
                self.assertTrue(base64.b64decode(r['rows'][0]['raw_base64']))
                if t.raw is not None:
                    self.assertEqual(base64.b64decode(r['rows'][0]['raw_base64']), t.raw)
                if failure != 'both-settlement-saves':
                    self.assertTrue(r['http_settled'])
                    self.assertEqual(r['stopped_error_type'], expected.__name__)

    def test_settlement_save_error_without_primary_is_reported_after_unload(self):
        dumps = screen.json.dumps
        t = Transport()
        def fail_save(data, *args, **kwargs):
            if isinstance(data, dict) and 'screen_elapsed_seconds' in data:
                raise OSError('synthetic final save failure')
            return dumps(data, *args, **kwargs)
        with patch.object(screen.json, 'dumps', side_effect=fail_save):
            with self.assertRaisesRegex(OSError, 'synthetic final save failure'):
                self.run_screen(t)
        self.assertEqual(t.paths[-2:], ['/unload', '/health'])
        self.assertEqual(self.result()['model_calls'], 4)
        self.assertFalse(self.result()['unknown_outcome'])

    def test_callers_handled_exception_does_not_hide_collectors_save_error(self):
        dumps = screen.json.dumps
        t = Transport()
        def fail_save(data, *args, **kwargs):
            if isinstance(data, dict) and 'screen_elapsed_seconds' in data:
                raise OSError('synthetic final save failure')
            return dumps(data, *args, **kwargs)
        try:
            raise LookupError('caller context, not a collector failure')
        except LookupError:
            with patch.object(screen.json, 'dumps', side_effect=fail_save):
                with self.assertRaisesRegex(OSError, 'synthetic final save failure'):
                    self.run_screen(t)
        self.assertEqual(t.paths[-2:], ['/unload', '/health'])

    def test_callable_rejects_caller_replacement_manifest_before_receipt(self):
        cells = json.loads(self.inputs.read_text())
        cells['cells'][0]['source'] += ' '
        cells['cells'][0]['expected'] += ' '
        self.inputs.write_text(json.dumps(cells))
        changed_hash = screen.digest(self.inputs.read_bytes())
        t = Transport()
        with self.assertRaisesRegex(ValueError, 'manifest changed'):
            screen.collect(self.inputs, changed_hash, self.output, 't' * 32, admission(),
                           opener=t, wall_clock=lambda: NOW, deck_observer=lambda: DECK)
        self.assertEqual(t.paths, [])
        self.assertFalse(self.output.exists())

    def test_admission_rejects_before_network_and_preserves_gates(self):
        changes = [lambda a: a['memory'].update(available_GiB=5.49),
            lambda a: a.update(vision_lock_free=False),
            lambda a: a.update(source_commit='wrong'),
            lambda a: a.update(copied_service_sha256='wrong'),
            lambda a: a.update(source_service_sha256='wrong'),
            lambda a: a['health'].update(loaded=True),
            lambda a: a.update(at=datetime.datetime.fromtimestamp(NOW-61, datetime.timezone.utc).isoformat()),
            lambda a: a.update(at=datetime.datetime.fromtimestamp(NOW+1, datetime.timezone.utc).isoformat()),
            lambda a: a['memory'].update(available_GiB=True)]
        for index, mutate in enumerate(changes):
            with self.subTest(index=index):
                self.output = self.root / f'admit-{index}.json'
                a = admission(); mutate(a); t = Transport()
                with self.assertRaises(ValueError):
                    self.run_screen(t, observation=a)
                self.assertEqual(t.paths, [])
                self.assertFalse(self.output.exists())

    def test_admission_can_expire_during_initial_health(self):
        t = Transport()
        with patch.object(screen.time, 'time', return_value=NOW):
            times = iter([NOW, NOW+61])
            with self.assertRaisesRegex(ValueError, 'Stale'):
                screen.collect(self.inputs, self.inputs_hash, self.output, 't'*32, admission(),
                    opener=t, wall_clock=lambda: next(times), deck_observer=lambda: DECK)
        self.assertEqual(t.paths, ['/health'])

    def test_late_final_response_retained_but_screen_incomplete(self):
        now = [0.0]
        def advance():
            if len(t.payloads) == 4:
                now[0] = 601.0
        t = Transport(on_call=advance)
        with self.assertRaisesRegex(TimeoutError, 'after response'):
            self.run_screen(t, clock=lambda: now[0])
        r = self.result()
        self.assertEqual(r['model_calls'], 4)
        self.assertEqual(len(r['rows']), 4)
        self.assertTrue(r['rows'][-1]['useful_grouping'])
        self.assertFalse(r['completed'] or r['unknown_outcome'])
        self.assertEqual(r['screen_elapsed_seconds'], 601)
        self.assertTrue(r['http_settled'])

    def test_settlement_failure_preserves_primary_results(self):
        result = self.run_screen(Transport(unload_fault=True))
        self.assertTrue(result['completed'])
        self.assertEqual(result['model_calls'], 4)
        self.assertEqual(result['settlement_error_type'], 'OSError')
        self.assertEqual(len(self.result()['rows']), 4)
        self.assertTrue(result['deck_preserved'])

    def test_deck_observation_failure_cannot_hide_known_primary_error(self):
        count = [0]
        def observer():
            count[0] += 1
            if count[0] == 2:
                raise OSError('no final observation')
            return DECK
        t = Transport(raw=b'bad-json')
        with self.assertRaises(ValueError):
            self.run_screen(t, deck_observer=observer)
        r = self.result()
        self.assertEqual(r['stopped_error_type'], 'JSONDecodeError')
        self.assertEqual(r['deck_observation_error_type'], 'OSError')
        self.assertTrue(r['http_settled'])

    def test_input_hash_order_and_scorer_drift_before_receipt(self):
        self.inputs.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'manifest changed'):
            self.run_screen(Transport())
        self.assertFalse(self.output.exists())

    def test_runtime_module_drift_before_receipt(self):
        with patch.dict(screen.MODULE_HASHES, {'bonsai_normalizer.py': 'wrong'}):
            with self.assertRaisesRegex(ValueError, 'module drift'):
                self.run_screen(Transport())
        self.assertFalse(self.output.exists())

    def test_invalid_surrogate_response_keeps_raw_receipt_and_exact_source(self):
        t = Transport(content='\ud800')
        with self.assertRaisesRegex(ValueError, 'Unexpected paragraph client outcome'):
            self.run_screen(t)
        r = self.result()
        self.assertFalse(r['unknown_outcome'])
        self.assertEqual(r['rows'][0]['returned'], SOURCE)
        self.assertEqual(r['rows'][0]['metadata']['reason'], 'invalid_content_encoding')
        self.assertTrue(r['http_settled'])
        self.assertEqual(r['model_calls'], 1)

    def test_request_timeout_is_bounded_by_remaining_budget(self):
        now = [0.0]
        count = [0]
        def clock():
            count[0] += 1
            if count[0] == 4:
                now[0] = 595.0
            return now[0]
        t = Transport()
        self.run_screen(t, clock=clock)
        self.assertEqual(t.timeouts, [5.0] * 4)

    def test_payload_drift_is_not_counted_as_a_submission(self):
        original = screen.BonsaiParagraphStructurer._messages_for_source
        calls = [0]
        def messages(editor, source):
            calls[0] += 1
            result = original(editor, source)
            if calls[0] == 2:
                result[0]['content'] += ' drift'
            return result
        t = Transport()
        with patch.object(screen.BonsaiParagraphStructurer, '_messages_for_source', messages):
            with self.assertRaisesRegex(ValueError, 'not submitted'):
                self.run_screen(t)
        self.assertEqual(len(t.payloads), 0)
        self.assertEqual(self.result()['model_calls'], 0)
        self.assertFalse(self.result()['unknown_outcome'])

    def test_dry_run_validates_without_network_result_or_token(self):
        args = ['screen', '--inputs', str(self.inputs), '--inputs-sha256', self.inputs_hash,
                '--output', str(self.output)]
        with patch.object(screen, 'INPUTS_SHA256', self.inputs_hash), patch.object(sys, 'argv', args), \
                patch('sys.stdout', new_callable=io.StringIO) as stdout:
            screen.main()
        self.assertFalse(self.output.exists())
        self.assertEqual(json.loads(stdout.getvalue())['model_calls'], 0)

    def test_duplicate_client_submission_is_rejected_before_second_transport(self):
        original = screen.BonsaiParagraphStructurer.normalize
        def twice(editor, source):
            original(editor, source)
            return original(editor, source)
        t = Transport()
        with patch.object(screen.BonsaiParagraphStructurer, 'normalize', twice):
            with self.assertRaises(ValueError):
                self.run_screen(t)
        self.assertEqual(len(t.payloads), 1)
        self.assertFalse(self.result()['unknown_outcome'])


if __name__ == '__main__':
    unittest.main()
