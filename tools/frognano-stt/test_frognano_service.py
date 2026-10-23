"""Model/network-free stdlib checks for the fixed FrogNano service contract."""
from http.client import HTTPMessage
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

SPEC = importlib.util.spec_from_file_location('frognano_service', Path(__file__).with_name('frognano_service.py'))
s = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(s)


def request():
    return dict(model=s.MODEL_ID, messages=[{'role': 'system', 'content': s.SYSTEM_PROMPT},
                {'role': 'user', 'content': 'Новый синтетический текст, срок 24 дня.'}],
                max_tokens=512, stream=False, **s.SAMPLER)


def response(text='  Точный текст.\n\n', token=248046, finish='stop', generation=1):
    return SimpleNamespace(text=text, token=token, finish_reason=finish,
                           prompt_tokens=3, generation_tokens=generation)


class ValidationTests(unittest.TestCase):
    def test_valid_sampler_and_original_text(self):
        payload = request()
        messages, maximum = s.parse_request(payload)
        self.assertIs(messages, payload['messages'])
        self.assertEqual(maximum, 512)
        payload['revision'] = s.REVISION
        s.parse_request(payload)

    def test_profile_rejections(self):
        cases = [None, [], {}, {'model': 'wrong'}, {'revision': 'wrong'}, {'stream': True},
                 {'stream': 0}, {'max_tokens': True}, {'max_tokens': 513}, {'max_tokens': 0},
                 {'tools': []}, {'images': []}, {'response_format': {}}, {'seed': 42.0},
                 {'seed': True}, {'top_k': 20.0}, {'temperature': float('nan')},
                 {'temperature': 0.1}, {'repetition_penalty': False}]
        for changes in cases:
            payload = request()
            if isinstance(changes, dict):
                payload.update(changes)
                if changes == {}:
                    payload = {}
            else:
                payload = changes
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                s.parse_request(payload)

    def test_exact_messages(self):
        for messages in ([], request()['messages'] * 2,
                         [{'role': 'system', 'content': s.SYSTEM_PROMPT + ' '}, {'role': 'user', 'content': 'x'}],
                         [{'role': 'system', 'content': s.SYSTEM_PROMPT}, {'role': 'user', 'content': []}],
                         [{'role': 'system', 'content': s.SYSTEM_PROMPT}, {'role': 'user', 'content': ''}],
                         [{'role': 'system', 'content': s.SYSTEM_PROMPT}, {'role': 'user', 'content': 'a' * 6001}],
                         [{'role': 'system', 'content': s.SYSTEM_PROMPT, 'name': 'x'}, {'role': 'user', 'content': 'x'}]):
            with self.subTest(messages=messages), self.assertRaises(ValueError):
                s.parse_request(dict(request(), messages=messages))

    def test_resource_boundaries(self):
        s.resource_check({'available_GiB': 6.5, 'swap_GiB': 3}, 3, admission=True)
        s.resource_check({'available_GiB': 2, 'swap_GiB': 3.25}, 3)
        for available, swap, initial, admission in ((6.49, 3, 3, True), (1.99, 3, 3, False),
                (9, 3.251, 3, False), (float('nan'), 0, 0, False), (9, -1, 0, False)):
            with self.assertRaises(MemoryError):
                s.resource_check({'available_GiB': available, 'swap_GiB': swap}, initial, admission)

    def test_native_memory_parse(self):
        with patch.object(s.subprocess, 'check_output', side_effect=[
                'total = 1024.00M used = 256.00M free = 768.00M',
                'Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free: 100.\nPages inactive: 200.\nPages speculative: 300.\n']):
            self.assertEqual(s.memory(), {'available_GiB': 600 * 16384 / s.GIB, 'swap_GiB': 0.25})


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = s.Engine('/model', '/setup', '/runtime', '/packages', 'a' * 64)
        self.lock = MagicMock()
        self.mx = MagicMock()
        self.model = object()
        self.tokenizer = MagicMock()
        self.tokenizer.eos_token_ids = [248044, 248046]
        self.tokenizer.convert_tokens_to_ids.side_effect = lambda t: {'<|im_end|>': 248046, '<|endoftext|>': 248044}[t]
        self.tokenizer.chat_template = 'original-template'
        self.tokenizer.apply_chat_template.side_effect = lambda messages, tokenize, **kw: (
            [1, 2, 3] if tokenize else '<|im_start|>system\nfixed<|im_start|>assistant\n<think>\n\n</think>\n\n')
        self.tokenizer.encode.return_value = [1, 2, 3]
        self.load = MagicMock(return_value=(self.model, self.tokenizer))
        self.events = [response()]
        self.generator = MagicMock()
        self.generator.__iter__.side_effect = lambda: iter(self.events)
        self.stream = MagicMock(return_value=self.generator)
        self.sampler = MagicMock(return_value='greedy')
        self.verify = self.enter(patch.object(self.engine, 'verify'))
        self.native = self.enter(patch.object(s, 'native_modules', return_value=(self.mx, self.load, self.stream, self.sampler)))
        self.flock = self.enter(patch.object(s.fcntl, 'flock'))
        self.open = self.enter(patch.object(Path, 'open', return_value=self.lock))
        self.enter(patch.object(Path, 'read_text', return_value='original-template'))
        self.mem = self.enter(patch.object(s, 'memory', return_value={'available_GiB': 8, 'swap_GiB': 1}))
        self.collect = self.enter(patch.object(s.gc, 'collect'))
        self.enter(patch.object(s.time, 'monotonic', return_value=0))

    def enter(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def assert_clean(self, native=True, generator=True):
        self.lock.close.assert_called_once_with()
        self.collect.assert_called_once_with()
        if native:
            self.assertEqual(self.mx.clear_cache.call_count, 2)
        if generator:
            self.generator.close.assert_called_once_with()

    def test_success_exact_bytes_and_profile(self):
        output = '  <think>not repaired</think>\r\n```\nПрямая речь.  '
        self.events = [response(output)]
        result = self.engine.infer(request())
        self.assertEqual(result['choices'][0]['message']['content'].encode(), output.encode())
        self.assertEqual(result['choices'][0]['finish_reason'], 'stop')
        self.assertEqual(result['model'], s.MODEL_ID)
        self.assertEqual(result['revision'], s.REVISION)
        self.assertEqual(result['bonsai']['revision'], s.REVISION)
        self.assertEqual(result['usage'], {'prompt_tokens': 3, 'completion_tokens': 1, 'total_tokens': 4})
        self.load.assert_called_once_with('/model', tokenizer_config={'trust_remote_code': False, 'local_files_only': True}, lazy=False, trust_remote_code=False)
        self.flock.assert_called_once_with(self.lock, s.fcntl.LOCK_EX | s.fcntl.LOCK_NB)
        self.mx.random.seed.assert_called_once_with(42)
        self.sampler.assert_called_once_with(temp=0.0)
        self.stream.assert_called_once_with(self.model, self.tokenizer, prompt=[1, 2, 3], max_tokens=512, sampler='greedy', prefill_step_size=512)
        self.assertEqual(self.mem.call_count, 5)
        self.assert_clean()

    def test_fresh_load_per_request(self):
        self.engine.infer(request())
        self.engine.infer(request())
        self.assertEqual(self.load.call_count, 2)
        self.assertEqual(self.mx.clear_cache.call_count, 4)

    def test_validation_before_verification_or_lock(self):
        with self.assertRaises(ValueError):
            self.engine.infer(dict(request(), tools=[]))
        self.verify.assert_not_called()
        self.open.assert_not_called()

    def test_hash_error_prevents_native_import(self):
        self.verify.side_effect = RuntimeError('pin')
        with self.assertRaises(RuntimeError):
            self.engine.infer(request())
        self.native.assert_not_called()
        self.open.assert_not_called()

    def test_busy_lock(self):
        self.flock.side_effect = BlockingIOError()
        with self.assertRaises(BlockingIOError):
            self.engine.infer(request())
        self.native.assert_not_called()
        self.assert_clean(native=False, generator=False)

    def test_low_admission(self):
        self.mem.return_value['available_GiB'] = 6.49
        with self.assertRaises(MemoryError):
            self.engine.infer(request())
        self.native.assert_not_called()
        self.assert_clean(native=False, generator=False)

    def test_failed_load(self):
        self.load.side_effect = RuntimeError('native path details')
        with self.assertRaises(RuntimeError):
            self.engine.infer(request())
        self.assert_clean(generator=False)
        self.load.assert_called_once()

    def test_native_import_failure_releases_lock(self):
        self.native.side_effect = ImportError('native missing')
        with self.assertRaises(ImportError):
            self.engine.infer(request())
        self.assert_clean(native=False, generator=False)

    def test_preload_admission_rechecked(self):
        self.mem.side_effect = [{'available_GiB': 8, 'swap_GiB': 1},
                               {'available_GiB': 6.4, 'swap_GiB': 1}]
        with self.assertRaises(MemoryError):
            self.engine.infer(request())
        self.load.assert_not_called()
        self.lock.close.assert_called_once_with()
        self.mx.clear_cache.assert_called_once_with()

    def test_stream_failure_releases_everything(self):
        def events():
            yield response('partial')
            raise RuntimeError('native generation failure')
        self.generator.__iter__.side_effect = events
        with self.assertRaises(RuntimeError):
            self.engine.infer(request())
        self.assert_clean()

    def test_token_budget(self):
        self.tokenizer.encode.return_value = [1] * 3073
        self.tokenizer.apply_chat_template.side_effect = lambda messages, tokenize, **kw: [1] * 3073 if tokenize else '<|im_start|>assistant\n<think>\n\n</think>\n\n'
        with self.assertRaises(ValueError):
            self.engine.infer(request())
        self.stream.assert_not_called()
        self.assert_clean(generator=False)

    def test_known_eos_required_not_length(self):
        for last in (response(finish='length'), response(token=12), response(token=True),
                     response(generation=513), response(generation=True), response(finish=None)):
            self.events = [last]
            with self.subTest(last=last), self.assertRaises(RuntimeError):
                self.engine.infer(request())

    def test_empty_generation(self):
        self.events = []
        with self.assertRaises(RuntimeError):
            self.engine.infer(request())
        self.assert_clean()

    def test_resource_every_response(self):
        self.events = [response('a'), response('b')]
        self.mem.side_effect = [{'available_GiB': 8, 'swap_GiB': 1}] * 4 + [{'available_GiB': 8, 'swap_GiB': 1.26}]
        with self.assertRaises(MemoryError):
            self.engine.infer(request())
        self.assertEqual(self.mem.call_count, 5)
        self.assert_clean()

    def test_deadline_after_native_load(self):
        self.load.side_effect = lambda *a, **kw: (setattr(s.time.monotonic, 'return_value', 20) or (self.model, self.tokenizer))
        with self.assertRaises(TimeoutError):
            self.engine.infer(request())
        self.assert_clean(generator=False)

    def test_deadline_includes_cleanup(self):
        self.generator.close.side_effect = lambda: setattr(s.time.monotonic, 'return_value', 20)
        with self.assertRaises(TimeoutError):
            self.engine.infer(request())
        self.assert_clean()

    def test_deadline_during_generation(self):
        def events():
            yield response('a')
            s.time.monotonic.return_value = 20
            yield response('b')
        self.generator.__iter__.side_effect = events
        with self.assertRaises(TimeoutError):
            self.engine.infer(request())
        self.assert_clean()

    def test_cleanup_failures_still_release_lock(self):
        for target in (self.generator.close, self.collect, self.mx.clear_cache):
            with self.subTest(target=target):
                target.side_effect = RuntimeError('cleanup')
                with self.assertRaises(RuntimeError):
                    self.engine.infer(request())
                target.side_effect = None
        self.assertEqual(self.lock.close.call_count, 3)
        self.assertEqual(self.mx.clear_cache.call_count, 6)

    def test_invalid_eos_and_template(self):
        self.tokenizer.eos_token_ids = [2]
        with self.assertRaises(RuntimeError):
            self.engine.infer(request())
        self.stream.assert_not_called()
        self.assert_clean(generator=False)

    def test_original_template_and_disabled_thinking_required(self):
        self.tokenizer.chat_template = 'patched-template'
        with self.assertRaises(RuntimeError):
            self.engine.infer(request())
        self.tokenizer.chat_template = 'original-template'
        self.tokenizer.apply_chat_template.side_effect = lambda *a, **kw: '<|im_start|>assistant\n<think>reasoning'
        with self.assertRaises(RuntimeError):
            self.engine.infer(request())
        self.stream.assert_not_called()


class ManifestTests(unittest.TestCase):
    def test_manifest_hashes_checked_before_parsing(self):
        engine = s.Engine('/model', '/setup', '/runtime', '/packages', 'a' * 64)
        with patch.object(s, 'digest_file', return_value='bad'), patch.object(Path, 'read_bytes') as read:
            with self.assertRaises(RuntimeError):
                engine.verify(lambda: None)
            read.assert_not_called()
        with patch.object(s, 'digest_file', side_effect=[s.SETUP_SHA256, 'bad']), patch.object(Path, 'read_bytes') as read:
            with self.assertRaises(RuntimeError):
                engine.verify(lambda: None)
            read.assert_not_called()

    def test_artifact_and_relative_home_runtime_verified(self):
        engine = s.Engine('/model', '/setup', '/runtime', '/packages', 'a' * 64)
        setup = {'revision': s.REVISION, 'files': {'weights.safetensors': {'bytes': 2, 'sha256': 'b' * 64}}}
        runtime = {'files': {'.localforge/overlay/mlx_lm/__init__.py': 'c' * 64}}
        with patch.object(s, 'digest_file', side_effect=[s.SETUP_SHA256, 'a' * 64, 'b' * 64, 'c' * 64]) as digest, patch.object(Path, 'read_bytes', side_effect=[json.dumps(setup).encode(), json.dumps(runtime).encode()]), patch.object(s, 'checked_path', side_effect=lambda root, name: root / name), patch.object(Path, 'stat', return_value=SimpleNamespace(st_size=2)), patch.object(Path, 'home', return_value=Path('/HOME')):
            engine.verify(lambda: None)
            self.assertEqual(digest.call_args_list[-1].args[0], Path('/HOME/.localforge/overlay/mlx_lm/__init__.py'))

    def test_model_and_runtime_drift_are_rejected(self):
        engine = s.Engine('/model', '/setup', '/runtime', '/packages', 'a' * 64)
        setup = {'revision': s.REVISION, 'files': {'weights.safetensors': {'bytes': 2, 'sha256': 'b' * 64}}}
        runtime = {'files': {'.localforge/overlay/mlx_lm/__init__.py': 'c' * 64}}
        for hashes, size in (([s.SETUP_SHA256, 'a' * 64, 'bad'], 2),
                              ([s.SETUP_SHA256, 'a' * 64], 3),
                              ([s.SETUP_SHA256, 'a' * 64, 'b' * 64, 'bad'], 2)):
            with self.subTest(hashes=hashes, size=size), patch.object(s, 'digest_file', side_effect=hashes), patch.object(Path, 'read_bytes', side_effect=[json.dumps(setup).encode(), json.dumps(runtime).encode()]), patch.object(s, 'checked_path', side_effect=lambda root, name: root / name), patch.object(Path, 'stat', return_value=SimpleNamespace(st_size=size)):
                with self.assertRaises(RuntimeError):
                    engine.verify(lambda: None)

    def test_digest_is_chunked_and_checks_deadline(self):
        handle = MagicMock()
        handle.__enter__.return_value = handle
        handle.read.side_effect = [b'abc', b'']
        check = MagicMock()
        with patch.object(Path, 'open', return_value=handle):
            self.assertEqual(s.digest_file(Path('/weights'), check),
                'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
        self.assertEqual(check.call_count, 2)
        self.assertEqual(handle.read.call_args.args, (8 * 1024 * 1024,))

    def test_no_path_escape(self):
        for path in ('../file', '/absolute', 'dir/../file'):
            with self.assertRaises(RuntimeError):
                s.checked_path(Path('/root'), path)

    def test_overlay_rejects_wrong_native_origin(self):
        with patch.object(Path, 'resolve', return_value=Path('/overlay')), patch.object(s.importlib.util, 'find_spec', return_value=SimpleNamespace(origin=None)), patch.object(s.importlib, 'import_module') as imp:
            original = list(s.sys.path)
            with self.assertRaises(RuntimeError):
                s.native_modules(Path('/overlay'))
            self.assertEqual(s.sys.path, original)
            imp.assert_not_called()

    def test_overlay_must_match_manifest_covered_root(self):
        with patch.object(Path, 'home', return_value=Path('/HOME')), patch.object(
                Path, 'resolve', autospec=True, side_effect=lambda p, **kw: p), patch.object(
                s.importlib.util, 'find_spec') as spec, patch.object(s.importlib, 'import_module') as imp:
            with self.assertRaisesRegex(RuntimeError, 'overlay'):
                s.native_modules(Path('/unverified-overlay'))
            spec.assert_not_called()
            imp.assert_not_called()

    def test_deadline_ceiling(self):
        for deadline in (0, -1, 20.01, 21, 60, float('nan'), True):
            with self.assertRaises(ValueError):
                s.Engine('/m', '/s', '/r', '/p', 'a' * 64, deadline)


class CLITests(unittest.TestCase):
    def argv(self):
        return ['frognano_service.py', '--host', '100.100.100.100', '--model-path', '/model',
                '--setup-manifest', '/setup', '--runtime-manifest', '/runtime',
                '--runtime-manifest-sha256', 'a' * 64, '--packages', '/packages', '--token-file', '/token']

    def test_cli_uses_serial_server_and_closes(self):
        with patch.object(s.sys, 'argv', self.argv()), patch.object(Path, 'read_text', return_value='a' * 32), patch.object(s, 'Engine') as engine, patch.object(s, 'Server') as server:
            s.main()
            server.assert_called_once_with(('100.100.100.100', 8093), s.Handler)
            engine.assert_called_once_with(Path('/model'), Path('/setup'), Path('/runtime'), Path('/packages'), 'a' * 64, 20)
            server.return_value.serve_forever.assert_called_once_with(poll_interval=1)
            server.return_value.server_close.assert_called_once_with()

    def test_cli_rejects_non_tailnet_or_bad_token(self):
        for host, token in (('0.0.0.0', 'a' * 32), ('127.0.0.1', 'a' * 32),
                            ('100.100.100.100', 'short'), ('100.100.100.100', 'a' * 32 + ' secret')):
            argv = self.argv()
            argv[2] = host
            with self.subTest(host=host, token_length=len(token)), patch.object(s.sys, 'argv', argv), patch.object(Path, 'read_text', return_value=token), patch.object(s, 'Server') as server, patch('sys.stderr', new_callable=io.StringIO):
                with self.assertRaises(SystemExit):
                    s.main()
                server.assert_not_called()


class HTTPTests(unittest.TestCase):
    def handler(self, payload=None, method='POST', path='/v1/chat/completions', headers=None, raw=None):
        handler = object.__new__(s.Handler)
        handler.server = SimpleNamespace(token='a' * 32, engine=MagicMock())
        handler.command, handler.path = method, path
        handler.headers = HTTPMessage()
        raw = json.dumps(request() if payload is None else payload, ensure_ascii=False).encode() if raw is None else raw
        values = {'Authorization': 'Bearer ' + 'a' * 32, 'Content-Length': str(len(raw)), 'Content-Type': 'application/json'}
        values.update(headers or {})
        for name, value in values.items():
            if value is not None:
                handler.headers[name] = value
        handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
        handler.send_json = MagicMock()
        return handler

    def test_auth_does_not_infer_or_read_body(self):
        for auth in (None, 'Bearer wrong', 'Bearer ' + 'a' * 32 + ' '):
            h = self.handler(headers={'Authorization': auth})
            h.dispatch()
            h.send_json.assert_called_once_with(401, {'error': 'Unauthorized'})
            h.server.engine.infer.assert_not_called()
            self.assertEqual(h.rfile.tell(), 0)
        h = self.handler()
        h.headers['Authorization'] = 'Bearer ' + 'a' * 32
        h.dispatch()
        self.assertEqual(h.send_json.call_args.args[0], 401)

    def test_health_and_models_never_load(self):
        for path in ('/health', '/v1/models'):
            h = self.handler(method='GET', path=path)
            h.dispatch()
            self.assertEqual(h.send_json.call_args.args[0], 200)
            h.server.engine.infer.assert_not_called()
            self.assertEqual(h.rfile.tell(), 0)

    def test_paths_and_methods(self):
        for method, path, status in (('POST', '/bad', 404), ('GET', '/v1/chat/completions', 405),
                                    ('PUT', '/health', 405), ('GET', '/health?x', 404)):
            h = self.handler(method=method, path=path)
            h.dispatch()
            self.assertEqual(h.send_json.call_args.args[0], status)
            h.server.engine.infer.assert_not_called()

    def test_body_rejections(self):
        for headers, raw in (({'Content-Length': '0'}, b''), ({'Content-Length': str(s.MAX_BODY + 1)}, b''),
                ({'Content-Length': '2'}, b'{'), ({'Content-Length': None}, b''),
                ({'Content-Length': '+2'}, b'{}'), ({'Transfer-Encoding': 'chunked'}, b'{}'),
                ({'Content-Type': 'text/plain'}, b'{}'), ({}, b'\xff'), ({}, b'{'),
                ({}, b'{"x": NaN}'), ({}, b'{"x": 1, "x": 2}')):
            h = self.handler(headers=headers, raw=raw)
            h.dispatch()
            self.assertEqual(h.send_json.call_args.args[0], 400)
            h.server.engine.infer.assert_not_called()
        h = self.handler()
        h.headers['Content-Length'] = '1'
        h.dispatch()
        self.assertEqual(h.send_json.call_args.args[0], 400)

    def test_errors_sanitized_no_retry(self):
        for error, status in ((ValueError('secret transcript'), 400),
                              (MemoryError('secret path'), 503), (TimeoutError('secret token'), 503)):
            h = self.handler()
            h.server.engine.infer.side_effect = error
            h.dispatch()
            self.assertEqual(h.send_json.call_args.args[0], status)
            self.assertNotIn('secret', str(h.send_json.call_args))
            h.server.engine.infer.assert_called_once()

    def test_success_passes_exact_payload_and_result(self):
        h = self.handler()
        h.server.engine.infer.return_value = {'content': '  сырой\r\n'}
        h.dispatch()
        h.server.engine.infer.assert_called_once_with(request())
        h.send_json.assert_called_once_with(200, {'content': '  сырой\r\n'})

    def test_socket_timeout(self):
        connection = MagicMock()
        with patch.object(s.HTTPServer, 'get_request', return_value=(connection, 'address')):
            server = object.__new__(s.Server)
            self.assertEqual(server.get_request(), (connection, 'address'))
            connection.settimeout.assert_called_once_with(s.SOCKET_TIMEOUT)

    def test_json_response_preserves_content(self):
        h = self.handler()
        h.send_response, h.send_header, h.end_headers = MagicMock(), MagicMock(), MagicMock()
        s.Handler.send_json(h, 200, {'text': '  Русский\r\n'})
        self.assertEqual(json.loads(h.wfile.getvalue()), {'text': '  Русский\r\n'})
        self.assertTrue(h.close_connection)


if __name__ == '__main__':
    unittest.main()
