"""Model/network-free stdlib checks for the fixed Bolt service contract.

Covers lifecycle/deadline/resource/auth/body/identity/template/drift/EOS/no-retry,
pinned GGUF hash, signal-as-BaseException, monitor-failure, cleanup-false-holds-lock,
deadline-includes-cleanup, no-redirects, runtime-path-outside-home,
plus -O (assert-free). No SSH, inference, private/audio access, Git mutation or
delegation.
"""
from http.client import HTTPMessage
import importlib.util
import io
import json
from pathlib import Path
import signal
import subprocess
import threading
from types import SimpleNamespace
import unittest
import urllib.request
from unittest.mock import MagicMock, patch, PropertyMock, call

SPEC = importlib.util.spec_from_file_location(
    'bolt_service', Path(__file__).with_name('bolt_service.py'))
s = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(s)


def request():
    return dict(model=s.MODEL_ID, messages=[
        {'role': 'system', 'content': s.SYSTEM_PROMPT},
        {'role': 'user', 'content': 'Новый синтетический текст, срок 24 дня.'}],
        max_tokens=512, stream=False, **s.SAMPLER)


def make_response(content='Точный текст.', finish_reason='stop', model=None,
                  prompt_tokens=10, completion_tokens=5, verbose=True):
    """Build a mock llama-server /v1/chat/completions response."""
    resp = {
        'model': model or s.MODEL_ID,
        'choices': [{
            'index': 0,
            'message': {'role': 'assistant', 'content': content},
            'finish_reason': finish_reason,
        }],
        'usage': {
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'total_tokens': prompt_tokens + completion_tokens,
        },
    }
    if verbose:
        resp['__verbose'] = {
            'content': content,
            'prompt': '<bos>' + '<|turn>system\n' + s.SYSTEM_PROMPT.strip() + '<turn|>\n'
                      '<|turn>user\nНовый синтетический текст, срок 24 дня.<turn|>\n<|turn>model\n',
            'generation_settings': {
                'chat_format': 'peg-gemma4',
                'generation_prompt': '<|turn>model\n',
            },
            'truncated': False,
            'stop_type': 'eos',
        }
    return resp


def make_props(model_alias=None, model_path='/path/to/model.gguf'):
    """Build mock /props response with model_alias and model_path."""
    return {
        'default_generation_settings': {
            'n_ctx': 4096,
            'model': model_alias or s.MODEL_ID,
        },
        'build_info': s.BUILD_INFO,
        'total_slots': 1,
        'chat_template': 'x',
        'model_path': model_path,
    }


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
        for messages in (
            [], request()['messages'] * 2,
            [{'role': 'system', 'content': s.SYSTEM_PROMPT + ' '}, {'role': 'user', 'content': 'x'}],
            [{'role': 'system', 'content': s.SYSTEM_PROMPT}, {'role': 'user', 'content': []}],
            [{'role': 'system', 'content': s.SYSTEM_PROMPT}, {'role': 'user', 'content': ''}],
            [{'role': 'system', 'content': s.SYSTEM_PROMPT}, {'role': 'user', 'content': 'a' * 6001}],
            [{'role': 'system', 'content': s.SYSTEM_PROMPT, 'name': 'x'}, {'role': 'user', 'content': 'x'}],
        ):
            with self.subTest(messages=messages), self.assertRaises(ValueError):
                s.parse_request(dict(request(), messages=messages))

    def test_resource_boundaries(self):
        s.resource_check({'available_GiB': 6.5, 'swap_GiB': 3}, 3, admission=True)
        s.resource_check({'available_GiB': 2, 'swap_GiB': 3.25}, 3)
        for available, swap, initial, admission in (
            (6.49, 3, 3, True), (1.99, 3, 3, False),
            (9, 3.251, 3, False), (float('nan'), 0, 0, False), (9, -1, 0, False),
        ):
            with self.assertRaises(MemoryError):
                s.resource_check({'available_GiB': available, 'swap_GiB': swap}, initial, admission)

    def test_native_memory_parse(self):
        with patch.object(s.subprocess, 'check_output', side_effect=[
                'total = 1024.00M used = 256.00M free = 768.00M',
                'Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free: 100.\nPages inactive: 200.\nPages speculative: 300.\n']):
            self.assertEqual(s.memory(), {'available_GiB': 600 * 16384 / s.GIB, 'swap_GiB': 0.25})


class TemplateTests(unittest.TestCase):
    def test_valid_gemma4_template(self):
        prompt = '<|turn>system\nHello<turn|>\n<|turn>user\nWorld<turn|>\n<|turn>model\n'
        s.validate_template(prompt, 'Hello', 'World', [2, 100, 200])

    def test_wrong_prompt_format(self):
        with self.assertRaises(RuntimeError):
            s.validate_template('wrong', 'Hello', 'World', [2, 100])

    def test_missing_bos(self):
        prompt = '<|turn>system\nHello<turn|>\n<|turn>user\nWorld<turn|>\n<|turn>model\n'
        with self.assertRaises(RuntimeError):
            s.validate_template(prompt, 'Hello', 'World', [100, 200])

    def test_duplicate_bos(self):
        prompt = '<|turn>system\nHello<turn|>\n<|turn>user\nWorld<turn|>\n<|turn>model\n'
        with self.assertRaises(RuntimeError):
            s.validate_template(prompt, 'Hello', 'World', [2, 2, 100])

    def test_empty_tokens(self):
        prompt = '<|turn>system\nHello<turn|>\n<|turn>user\nWorld<turn|>\n<|turn>model\n'
        with self.assertRaises(RuntimeError):
            s.validate_template(prompt, 'Hello', 'World', [])

    def test_token_budget_exceeded(self):
        prompt = '<|turn>system\nHello<turn|>\n<|turn>user\nWorld<turn|>\n<|turn>model\n'
        with self.assertRaises(RuntimeError):
            s.validate_template(prompt, 'Hello', 'World', [2] + [100] * 3072)


class PinnedGGUFHashTests(unittest.TestCase):
    """(1) GGUF hash must equal the pinned constant, not accept arbitrary computed hash."""

    def test_gguf_sha256_is_pinned(self):
        self.assertEqual(s.GGUF_SHA256, 'c8af2b8aea10a690a1d9491db744a9446660173cb38fc489612b556615a69612')
        self.assertEqual(s.GGUF_BYTES, 6180446208)

    def test_startup_rejects_wrong_gguf_hash(self):
        engine = s.Engine('/b', '/m', '/r', 'a' * 64)
        mock_stat = SimpleNamespace(st_size=s.GGUF_BYTES, st_ino=1, st_dev=2,
                                     st_mtime_ns=3, st_ctime_ns=4)
        # Binary hash matches, but GGUF hash doesn't match the pinned constant.
        with patch.object(s, 'digest_file', side_effect=[s.BINARY_SHA256, 'bad_gguf_hash']):
            with patch.object(Path, 'stat', return_value=mock_stat):
                with self.assertRaisesRegex(RuntimeError, 'GGUF hash does not match pinned'):
                    engine.verify_startup()

    def test_startup_rejects_wrong_gguf_size(self):
        engine = s.Engine('/b', '/m', '/r', 'a' * 64)
        mock_stat = SimpleNamespace(st_size=999, st_ino=1, st_dev=2,
                                     st_mtime_ns=3, st_ctime_ns=4)
        with patch.object(s, 'digest_file', side_effect=[s.BINARY_SHA256, s.GGUF_SHA256]):
            with patch.object(Path, 'stat', return_value=mock_stat):
                with self.assertRaisesRegex(RuntimeError, 'GGUF size does not match'):
                    engine.verify_startup()

    def test_startup_stat_stability_check(self):
        """Stat before/after full read must be stable."""
        engine = s.Engine('/b', '/m', '/r', 'a' * 64)
        stat_before = SimpleNamespace(st_size=s.GGUF_BYTES, st_ino=1, st_dev=2,
                                       st_mtime_ns=100, st_ctime_ns=4)
        stat_after = SimpleNamespace(st_size=s.GGUF_BYTES, st_ino=1, st_dev=2,
                                      st_mtime_ns=200, st_ctime_ns=4)  # mtime changed
        with patch.object(s, 'digest_file', side_effect=[s.BINARY_SHA256, s.GGUF_SHA256]):
            with patch.object(Path, 'stat', side_effect=[stat_before, stat_after]):
                with self.assertRaisesRegex(RuntimeError, 'changed during hash'):
                    engine.verify_startup()

    def test_stat_includes_ctime_ns(self):
        """Per-request stat must include ctime_ns when available."""
        engine = s.Engine('/b', '/m', '/r', 'a' * 64)
        mock_stat = SimpleNamespace(st_size=s.GGUF_BYTES, st_ino=1, st_dev=2,
                                     st_mtime_ns=3, st_ctime_ns=42)
        with patch.object(s, 'digest_file', side_effect=[s.BINARY_SHA256, s.GGUF_SHA256]):
            with patch.object(Path, 'stat', return_value=mock_stat):
                engine.verify_startup()
        self.assertEqual(engine.gguf_stat, (s.GGUF_BYTES, 1, 2, 3, 42))
        # Verify stat drift with changed ctime_ns.
        changed_stat = SimpleNamespace(st_size=s.GGUF_BYTES, st_ino=1, st_dev=2,
                                        st_mtime_ns=3, st_ctime_ns=99)
        with patch.object(Path, 'stat', return_value=changed_stat):
            with self.assertRaisesRegex(RuntimeError, 'stat identity drift'):
                engine.verify_stat_identity()


class EngineLifecycleTests(unittest.TestCase):
    """Tests for engine startup verification, stat drift, and deadline behavior."""

    def test_deadline_ceiling(self):
        for deadline in (0, -1, 18.01, 19, 60, float('nan'), True):
            with self.subTest(deadline=deadline), self.assertRaises(ValueError):
                s.Engine('/b', '/m', '/r', 'a' * 64, deadline)

    def test_invalid_manifest_sha(self):
        for sha in ('short', 'g' * 64, 'a' * 63, 'a' * 65):
            with self.subTest(sha=sha), self.assertRaises(ValueError):
                s.Engine('/b', '/m', '/r', sha)

    def test_valid_engine_creation(self):
        engine = s.Engine('/b', '/m', '/r', 'a' * 64, 18)
        self.assertEqual(engine.deadline_seconds, 18)
        self.assertIsNone(engine.gguf_sha256)
        self.assertIsNone(engine.gguf_stat)

    def test_startup_binary_drift(self):
        engine = s.Engine('/b', '/m', '/r', 'a' * 64)
        with patch.object(s, 'digest_file', return_value='bad'):
            with self.assertRaisesRegex(RuntimeError, 'Binary identity drift'):
                engine.verify_startup()

    def test_startup_success(self):
        engine = s.Engine('/b', '/m', '/r', 'a' * 64)
        mock_stat = SimpleNamespace(st_size=s.GGUF_BYTES, st_ino=1, st_dev=2,
                                     st_mtime_ns=3, st_ctime_ns=4)
        with patch.object(s, 'digest_file', side_effect=[s.BINARY_SHA256, s.GGUF_SHA256]):
            with patch.object(Path, 'stat', return_value=mock_stat):
                engine.verify_startup()
        self.assertEqual(engine.gguf_sha256, s.GGUF_SHA256)
        self.assertEqual(engine.gguf_stat, (s.GGUF_BYTES, 1, 2, 3, 4))

    def test_stat_identity_drift(self):
        engine = s.Engine('/b', '/m', '/r', 'a' * 64)
        engine.gguf_stat = (100, 1, 2, 3, 4)
        changed_stat = SimpleNamespace(st_size=101, st_ino=1, st_dev=2,
                                        st_mtime_ns=3, st_ctime_ns=4)
        with patch.object(Path, 'stat', return_value=changed_stat):
            with self.assertRaisesRegex(RuntimeError, 'stat identity drift'):
                engine.verify_stat_identity()

    def test_stat_identity_no_startup(self):
        engine = s.Engine('/b', '/m', '/r', 'a' * 64)
        with self.assertRaisesRegex(RuntimeError, 'Startup verification not completed'):
            engine.verify_stat_identity()


class EngineInferTests(unittest.TestCase):
    """Tests for the infer() method with mocked subprocess/network."""

    def setUp(self):
        s._shutdown = False  # reset shutdown flag
        self.engine = s.Engine('/binary', '/model.gguf', '/runtime', 'a' * 64)
        self.engine.gguf_sha256 = s.GGUF_SHA256
        self.engine.gguf_stat = (s.GGUF_BYTES, 1, 2, 3, 4)

        self.lock = MagicMock()
        self.proc = MagicMock()
        self.proc.pid = 12345
        self.proc.poll.return_value = 0  # safe default: "already exited"
        self.proc.wait.return_value = 0
        self.proc.returncode = 0

        self.text = request()['messages'][1]['content']
        self.rendered_prompt = (
            '<|turn>system\n' + s.SYSTEM_PROMPT.strip() + '<turn|>\n'
            '<|turn>user\n' + self.text.strip() + '<turn|>\n<|turn>model\n'
        )
        self.tokens = [2, 100, 200, 300, 400, 500, 600, 700, 800, 900]

        # Setup patches.
        self.patches = []

        self.p_stat = self._patch(s.Engine, 'verify_stat_identity')
        self.p_runtime = self._patch(s.Engine, 'verify_runtime_manifest')
        self.p_open = self._patch(Path, 'open', return_value=self.lock)
        self.p_flock = self._patch(s.fcntl, 'flock')
        self.p_mem = self._patch(s, 'memory', return_value={'available_GiB': 8, 'swap_GiB': 1})
        self.p_time = self._patch(s.time, 'monotonic', return_value=0)
        self.p_time_ns = self._patch(s.time, 'time_ns', return_value=123456789)
        self.p_socket = self._patch(s.socket, 'socket')
        self.p_socket.return_value.__enter__ = MagicMock(return_value=self.p_socket.return_value)
        self.p_socket.return_value.__exit__ = MagicMock(return_value=False)
        self.p_socket.return_value.getsockname.return_value = ('127.0.0.1', 54321)
        self.p_popen = self._patch(s.subprocess, 'Popen', return_value=self.proc)
        self.p_killpg = self._patch(s.os, 'killpg')
        self.p_resource = self._patch(s, 'resource_check')

        self.props_resp = make_props()
        self.inference_resp = make_response(prompt_tokens=len(self.tokens))

        def mock_api(port, endpoint, body=None, timeout=8):
            if endpoint == '/health':
                return {'status': 'ok'}
            elif endpoint == '/props':
                return self.props_resp
            elif endpoint == '/apply-template':
                return {'prompt': self.rendered_prompt}
            elif endpoint == '/tokenize':
                return {'tokens': self.tokens}
            elif endpoint == '/v1/chat/completions':
                return self.inference_resp
            raise RuntimeError(f'Unexpected API call: {endpoint}')

        self.p_api = self._patch(s, 'llama_api', side_effect=mock_api)
        # Patch template sha256 check to pass.
        self.p_sha = self._patch(s.hashlib, 'sha256')
        self.p_sha.return_value.hexdigest.return_value = s.TEMPLATE_SHA256

    def _patch(self, target, attr=None, **kwargs):
        if attr:
            p = patch.object(target, attr, **kwargs)
        else:
            p = patch(target, **kwargs)
        result = p.start()
        self.patches.append(p)
        return result

    def tearDown(self):
        s._shutdown = False
        for p in reversed(self.patches):
            p.stop()

    def test_success_returns_result(self):
        poll_values = iter([None, 0, 0])
        self.proc.poll.side_effect = lambda: next(poll_values, 0)
        result = self.engine.infer(request())
        self.assertEqual(result['model'], s.MODEL_ID)
        self.assertEqual(result['revision'], s.REVISION)
        self.assertEqual(result['choices'][0]['finish_reason'], 'stop')
        self.assertEqual(result['choices'][0]['message']['content'], 'Точный текст.')
        self.assertEqual(result['bolt']['gguf_sha256'], s.GGUF_SHA256)
        self.assertTrue(result['bolt']['cold'])
        self.assertFalse(result['bolt']['thinking'])
        self.assertIn('total_seconds', result['bolt'])
        # Resource telemetry present.
        self.assertIn('resources', result['bolt'])
        self.assertIn('before_GiB', result['bolt']['resources'])
        self.assertIn('after_GiB', result['bolt']['resources'])
        self.lock.close.assert_called()

    def test_validation_before_stat_check(self):
        with self.assertRaises(ValueError):
            self.engine.infer(dict(request(), tools=[]))
        self.p_stat.assert_not_called()
        self.p_open.assert_not_called()

    def test_stat_drift_prevents_lock(self):
        self.p_stat.side_effect = RuntimeError('GGUF stat identity drift')
        with self.assertRaises(RuntimeError):
            self.engine.infer(request())
        self.p_open.assert_not_called()

    def test_runtime_manifest_drift_prevents_lock(self):
        self.p_runtime.side_effect = RuntimeError('Runtime manifest drift')
        with self.assertRaises(RuntimeError):
            self.engine.infer(request())
        self.p_open.assert_not_called()

    def test_busy_lock_no_subprocess(self):
        self.p_flock.side_effect = BlockingIOError()
        with self.assertRaises(BlockingIOError):
            self.engine.infer(request())
        self.p_popen.assert_not_called()
        self.lock.close.assert_called()

    def test_low_admission_no_subprocess(self):
        self.p_resource.side_effect = MemoryError('Resource gate')
        with self.assertRaises(MemoryError):
            self.engine.infer(request())
        self.p_popen.assert_not_called()
        self.lock.close.assert_called()

    def test_child_crash_during_startup(self):
        self.proc.poll.return_value = 1  # process exited immediately
        with self.assertRaises(RuntimeError):
            self.engine.infer(request())
        self.lock.close.assert_called()

    def test_template_drift_raises(self):
        self.p_sha.return_value.hexdigest.return_value = 'wrong_hash'
        poll_values = iter([None, 0, 0])
        self.proc.poll.side_effect = lambda: next(poll_values, 0)
        with self.assertRaises(RuntimeError):
            self.engine.infer(request())
        self.lock.close.assert_called()

    def test_non_eos_finish_raises(self):
        self.inference_resp = make_response(finish_reason='length', prompt_tokens=len(self.tokens))
        poll_values = iter([None, 0, 0])
        self.proc.poll.side_effect = lambda: next(poll_values, 0)
        with self.assertRaises(RuntimeError):
            self.engine.infer(request())
        self.lock.close.assert_called()

    def test_truncated_output_raises(self):
        resp = make_response(prompt_tokens=len(self.tokens))
        resp['__verbose']['truncated'] = True
        self.inference_resp = resp
        poll_values = iter([None, 0, 0])
        self.proc.poll.side_effect = lambda: next(poll_values, 0)
        with self.assertRaises(RuntimeError):
            self.engine.infer(request())

    def test_reasoning_content_raises(self):
        resp = make_response(prompt_tokens=len(self.tokens))
        resp['choices'][0]['message']['reasoning_content'] = 'thinking...'
        self.inference_resp = resp
        poll_values = iter([None, 0, 0])
        self.proc.poll.side_effect = lambda: next(poll_values, 0)
        with self.assertRaises(RuntimeError):
            self.engine.infer(request())

    def test_empty_output_raises(self):
        self.inference_resp = make_response(content='', prompt_tokens=len(self.tokens))
        poll_values = iter([None, 0, 0])
        self.proc.poll.side_effect = lambda: next(poll_values, 0)
        with self.assertRaises(RuntimeError):
            self.engine.infer(request())

    def test_wrong_model_in_response_raises(self):
        self.inference_resp = make_response(model='wrong-model', prompt_tokens=len(self.tokens))
        poll_values = iter([None, 0, 0])
        self.proc.poll.side_effect = lambda: next(poll_values, 0)
        with self.assertRaises(RuntimeError):
            self.engine.infer(request())

    def test_no_verbose_raises(self):
        self.inference_resp = make_response(verbose=False, prompt_tokens=len(self.tokens))
        poll_values = iter([None, 0, 0])
        self.proc.poll.side_effect = lambda: next(poll_values, 0)
        with self.assertRaises(RuntimeError):
            self.engine.infer(request())

    def test_wrong_chat_format_raises(self):
        resp = make_response(prompt_tokens=len(self.tokens))
        resp['__verbose']['generation_settings']['chat_format'] = 'chatml'
        self.inference_resp = resp
        poll_values = iter([None, 0, 0])
        self.proc.poll.side_effect = lambda: next(poll_values, 0)
        with self.assertRaises(RuntimeError):
            self.engine.infer(request())

    def test_token_count_mismatch_raises(self):
        self.inference_resp = make_response(prompt_tokens=999)
        poll_values = iter([None, 0, 0])
        self.proc.poll.side_effect = lambda: next(poll_values, 0)
        with self.assertRaises(RuntimeError):
            self.engine.infer(request())

    def test_deadline_during_inference(self):
        """Deadline includes cleanup; work stops at work_deadline (13s for 18s budget)."""
        def time_api(port, endpoint, body=None, timeout=8):
            if endpoint == '/v1/chat/completions':
                s.time.monotonic.return_value = 13  # work_deadline reached
                return make_response(prompt_tokens=len(self.tokens))
            if endpoint == '/health':
                return {'status': 'ok'}
            if endpoint == '/props':
                return self.props_resp
            if endpoint == '/apply-template':
                return {'prompt': self.rendered_prompt}
            if endpoint == '/tokenize':
                return {'tokens': self.tokens}
            raise RuntimeError(f'Unexpected: {endpoint}')

        self.p_api.side_effect = time_api
        poll_values = iter([None, 0, 0])
        self.proc.poll.side_effect = lambda: next(poll_values, 0)
        with self.assertRaises(TimeoutError):
            self.engine.infer(request())
        self.lock.close.assert_called()

    def test_output_content_must_be_str(self):
        """Output must be str type, not int/list/dict."""
        resp = make_response(prompt_tokens=len(self.tokens))
        resp['choices'][0]['message']['content'] = 42
        self.inference_resp = resp
        poll_values = iter([None, 0, 0])
        self.proc.poll.side_effect = lambda: next(poll_values, 0)
        with self.assertRaises(RuntimeError):
            self.engine.infer(request())

    def test_single_choice_required(self):
        """Response must contain exactly one choice."""
        resp = make_response(prompt_tokens=len(self.tokens))
        resp['choices'].append(resp['choices'][0].copy())
        self.inference_resp = resp
        poll_values = iter([None, 0, 0])
        self.proc.poll.side_effect = lambda: next(poll_values, 0)
        with self.assertRaises(RuntimeError):
            self.engine.infer(request())

    def test_finite_token_usage_output_1_to_max(self):
        """completion_tokens must be 1..max_tokens."""
        resp = make_response(prompt_tokens=len(self.tokens), completion_tokens=0)
        resp['usage']['total_tokens'] = len(self.tokens)
        self.inference_resp = resp
        poll_values = iter([None, 0, 0])
        self.proc.poll.side_effect = lambda: next(poll_values, 0)
        with self.assertRaises(RuntimeError):
            self.engine.infer(request())

    def test_no_retry_single_api_call(self):
        """Inference is called exactly once, no retry on failure."""
        def fail_inference(port, endpoint, body=None, timeout=8):
            if endpoint == '/v1/chat/completions':
                raise ConnectionError('network down')
            if endpoint == '/health':
                return {'status': 'ok'}
            if endpoint == '/props':
                return self.props_resp
            if endpoint == '/apply-template':
                return {'prompt': self.rendered_prompt}
            if endpoint == '/tokenize':
                return {'tokens': self.tokens}
            raise RuntimeError(f'Unexpected: {endpoint}')

        self.p_api.side_effect = fail_inference
        poll_values = iter([None, 0, 0])
        self.proc.poll.side_effect = lambda: next(poll_values, 0)
        with self.assertRaises(ConnectionError):
            self.engine.infer(request())
        completions_calls = [c for c in self.p_api.call_args_list
                             if c[0][1] == '/v1/chat/completions']
        self.assertEqual(len(completions_calls), 1)


class SignalTests(unittest.TestCase):
    """(4) Signal uses BaseException/SystemExit-based shutdown; cannot be caught by except Exception."""

    def test_service_shutdown_is_system_exit(self):
        self.assertTrue(issubclass(s.ServiceShutdown, SystemExit))
        self.assertTrue(issubclass(s.ServiceShutdown, BaseException))
        self.assertFalse(issubclass(s.ServiceShutdown, Exception))

    def test_signal_not_caught_by_except_exception(self):
        """ServiceShutdown escapes except Exception handlers."""
        with self.assertRaises(SystemExit):
            try:
                raise s.ServiceShutdown('test')
            except Exception:
                self.fail('ServiceShutdown should not be caught by except Exception')

    def test_shutdown_flag_prevents_serving(self):
        engine = s.Engine('/b', '/m', '/r', 'a' * 64)
        engine.gguf_sha256 = s.GGUF_SHA256
        engine.gguf_stat = (s.GGUF_BYTES, 1, 2, 3, 4)
        s._shutdown = True
        try:
            with self.assertRaises(SystemExit):
                engine.infer(request())
        finally:
            s._shutdown = False


class SignalInstallOrderTests(unittest.TestCase):
    """(4) Signal handlers must be installed BEFORE verify_startup so SIGTERM during hashing terminates."""

    def test_signal_installed_before_verify_startup(self):
        call_order = []

        def track_signal(sig, handler):
            call_order.append(('signal', sig))

        def track_verify():
            call_order.append(('verify_startup',))

        argv = ['bolt_service.py', '--host', '100.100.100.100',
                '--binary-path', '/binary', '--model-path', '/model.gguf',
                '--runtime-manifest', '/runtime',
                '--runtime-manifest-sha256', 'a' * 64,
                '--token-file', '/token']
        with (patch.object(s.sys, 'argv', argv),
              patch.object(Path, 'read_text', return_value='a' * 32),
              patch.object(s, 'Engine') as engine_cls,
              patch.object(s, 'Server') as server_cls,
              patch.object(s.signal, 'signal', side_effect=track_signal)):
            engine_cls.return_value.verify_startup = track_verify
            s._shutdown = True  # so the serve loop exits immediately
            try:
                s.main()
            finally:
                s._shutdown = False
            # Find signal and verify_startup in call order.
            signal_indices = [i for i, c in enumerate(call_order) if c[0] == 'signal']
            verify_indices = [i for i, c in enumerate(call_order) if c[0] == 'verify_startup']
            self.assertTrue(signal_indices, 'Signal handlers not installed')
            self.assertTrue(verify_indices, 'verify_startup not called')
            # All signal installations must come before verify_startup.
            self.assertTrue(max(signal_indices) < min(verify_indices),
                            f'Signal installed after verify_startup: {call_order}')


class MonitorFailureTests(unittest.TestCase):
    """(5) Monitor errors after successful inference must be fatal."""

    def setUp(self):
        s._shutdown = False

    def tearDown(self):
        s._shutdown = False

    def test_monitor_error_after_inference_is_fatal(self):
        """Monitor failure concurrent with normal completion must raise.

        Post-cleanup resource_check is mandatory; if it fails, the result
        must not be returned even though inference completed normally.
        """
        engine = s.Engine('/binary', '/model.gguf', '/runtime', 'a' * 64)
        engine.gguf_sha256 = s.GGUF_SHA256
        engine.gguf_stat = (s.GGUF_BYTES, 1, 2, 3, 4)

        lock = MagicMock()
        proc = MagicMock()
        proc.pid = 12345
        # Process running during health loop, then exited for cleanup.
        poll_values = iter([None, 0, 0, 0])
        proc.poll.side_effect = lambda: next(poll_values, 0)
        proc.wait.return_value = 0

        text = request()['messages'][1]['content']
        rendered_prompt = (
            '<|turn>system\n' + s.SYSTEM_PROMPT.strip() + '<turn|>\n'
            '<|turn>user\n' + text.strip() + '<turn|>\n<|turn>model\n'
        )
        tokens = [2, 100, 200, 300, 400, 500, 600, 700, 800, 900]
        props_resp = make_props()
        inference_resp = make_response(prompt_tokens=len(tokens))

        def mock_api(port, endpoint, body=None, timeout=8):
            if endpoint == '/health':
                return {'status': 'ok'}
            elif endpoint == '/props':
                return props_resp
            elif endpoint == '/apply-template':
                return {'prompt': rendered_prompt}
            elif endpoint == '/tokenize':
                return {'tokens': tokens}
            elif endpoint == '/v1/chat/completions':
                return inference_resp
            raise RuntimeError(f'Unexpected: {endpoint}')

        with (patch.object(s.Engine, 'verify_stat_identity'),
              patch.object(s.Engine, 'verify_runtime_manifest'),
              patch.object(Path, 'open', return_value=lock),
              patch.object(s.fcntl, 'flock'),
              patch.object(s, 'memory', return_value={'available_GiB': 8, 'swap_GiB': 1}),
              patch.object(s.time, 'monotonic', return_value=0),
              patch.object(s.time, 'time_ns', return_value=123456789),
              patch.object(s.socket, 'socket') as mock_sock,
              patch.object(s.subprocess, 'Popen', return_value=proc),
              patch.object(s.os, 'killpg'),
              patch.object(s, 'llama_api', side_effect=mock_api),
              patch.object(s.hashlib, 'sha256') as mock_sha,
              patch.object(s, 'resource_check') as mock_rc):
            mock_sock.return_value.__enter__ = MagicMock(return_value=mock_sock.return_value)
            mock_sock.return_value.__exit__ = MagicMock(return_value=False)
            mock_sock.return_value.getsockname.return_value = ('127.0.0.1', 54321)
            mock_sha.return_value.hexdigest.return_value = s.TEMPLATE_SHA256

            # Make resource_check pass on admission but fail on post-cleanup.
            rc_calls = [0]

            def rc_side_effect(*args, **kwargs):
                rc_calls[0] += 1
                if rc_calls[0] > 1:
                    raise MemoryError('Post-cleanup resource gate')

            mock_rc.side_effect = rc_side_effect

            with self.assertRaises(MemoryError):
                engine.infer(request())


class CleanupFalseHoldsLockTests(unittest.TestCase):
    """(5) When terminate_child returns False (unreapable), lock must be held and serving must stop."""

    def setUp(self):
        s._shutdown = False

    def tearDown(self):
        s._shutdown = False

    def test_unreapable_child_holds_lock_stops_serving(self):
        engine = s.Engine('/binary', '/model.gguf', '/runtime', 'a' * 64)
        engine.gguf_sha256 = s.GGUF_SHA256
        engine.gguf_stat = (s.GGUF_BYTES, 1, 2, 3, 4)

        lock = MagicMock()
        proc = MagicMock()
        proc.pid = 12345
        # Process never exits — terminate_child returns False.
        proc.poll.return_value = None
        proc.wait.side_effect = subprocess.TimeoutExpired('cmd', 2)

        text = request()['messages'][1]['content']
        rendered_prompt = (
            '<|turn>system\n' + s.SYSTEM_PROMPT.strip() + '<turn|>\n'
            '<|turn>user\n' + text.strip() + '<turn|>\n<|turn>model\n'
        )
        tokens = [2, 100, 200, 300, 400, 500, 600, 700, 800, 900]
        props_resp = make_props()
        inference_resp = make_response(prompt_tokens=len(tokens))

        def mock_api(port, endpoint, body=None, timeout=8):
            if endpoint == '/health':
                return {'status': 'ok'}
            elif endpoint == '/props':
                return props_resp
            elif endpoint == '/apply-template':
                return {'prompt': rendered_prompt}
            elif endpoint == '/tokenize':
                return {'tokens': tokens}
            elif endpoint == '/v1/chat/completions':
                return inference_resp
            raise RuntimeError(f'Unexpected: {endpoint}')

        with (patch.object(s.Engine, 'verify_stat_identity'),
              patch.object(s.Engine, 'verify_runtime_manifest'),
              patch.object(Path, 'open', return_value=lock),
              patch.object(s.fcntl, 'flock'),
              patch.object(s, 'memory', return_value={'available_GiB': 8, 'swap_GiB': 1}),
              patch.object(s.time, 'monotonic', return_value=0),
              patch.object(s.time, 'time_ns', return_value=123456789),
              patch.object(s.socket, 'socket') as mock_sock,
              patch.object(s.subprocess, 'Popen', return_value=proc),
              patch.object(s.os, 'killpg'),
              patch.object(s, 'llama_api', side_effect=mock_api),
              patch.object(s.hashlib, 'sha256') as mock_sha,
              patch.object(s, 'resource_check')):
            mock_sock.return_value.__enter__ = MagicMock(return_value=mock_sock.return_value)
            mock_sock.return_value.__exit__ = MagicMock(return_value=False)
            mock_sock.return_value.getsockname.return_value = ('127.0.0.1', 54321)
            mock_sha.return_value.hexdigest.return_value = s.TEMPLATE_SHA256

            with self.assertRaisesRegex(RuntimeError, 'Failed to reap.*lock retained'):
                engine.infer(request())
            # Lock must NOT have been closed (held until process exit).
            lock.close.assert_not_called()
            # Shutdown flag must be set to prevent further serving.
            self.assertTrue(s._shutdown)


class ChildTerminationTests(unittest.TestCase):
    def test_terminate_none_proc(self):
        self.assertTrue(s.terminate_child(None))

    def test_terminate_already_exited(self):
        proc = MagicMock()
        proc.poll.return_value = 0
        self.assertTrue(s.terminate_child(proc))

    def test_terminate_normal_sigterm(self):
        proc = MagicMock()
        proc.poll.side_effect = [None, 0]
        proc.wait.return_value = 0
        with patch.object(s.os, 'killpg'):
            self.assertTrue(s.terminate_child(proc))

    def test_terminate_escalate_to_sigkill(self):
        proc = MagicMock()
        proc.poll.side_effect = [None, 0]
        proc.wait.side_effect = [subprocess.TimeoutExpired('cmd', 2), None]
        with patch.object(s.os, 'killpg'):
            self.assertTrue(s.terminate_child(proc))

    def test_terminate_unreapable(self):
        proc = MagicMock()
        proc.poll.side_effect = [None, None]
        proc.wait.side_effect = subprocess.TimeoutExpired('cmd', 2)
        with patch.object(s.os, 'killpg'):
            self.assertFalse(s.terminate_child(proc))

    def test_terminate_serialized_with_lock(self):
        """terminate_child with a lock serializes concurrent calls."""
        lock = threading.Lock()
        proc = MagicMock()
        proc.poll.return_value = 0
        self.assertTrue(s.terminate_child(proc, lock))


class ManifestTests(unittest.TestCase):
    """(2) checked_path root is binary.parent, not HOME; manifest covers binary+dylibs."""

    def test_no_path_escape(self):
        for path in ('../file', '/absolute', 'dir/../file'):
            with self.assertRaises(RuntimeError):
                s.checked_path(Path('/root'), path)

    def test_checked_path_resolves_relative_inside_root(self):
        """Safe relative entries resolve inside root."""
        with patch.object(Path, 'resolve', return_value=Path('/root/sub/file')):
            with patch.object(Path, 'is_file', return_value=True):
                # Should not raise.
                result = s.checked_path(Path('/root'), 'sub/file')

    def test_digest_chunked_and_checks_deadline(self):
        handle = MagicMock()
        handle.__enter__ = MagicMock(return_value=handle)
        handle.__exit__ = MagicMock(return_value=False)
        handle.read.side_effect = [b'abc', b'']
        check = MagicMock()
        with patch.object(Path, 'open', return_value=handle):
            result = s.digest_file(Path('/weights'), check)
            self.assertEqual(result,
                'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
        self.assertEqual(check.call_count, 2)

    def test_runtime_manifest_drift(self):
        engine = s.Engine('/b', '/m', '/r', 'a' * 64)
        with patch.object(s, 'digest_file', return_value='bad'):
            with self.assertRaises(RuntimeError):
                engine.verify_runtime_manifest(lambda: None)

    def test_runtime_manifest_requires_binary_coverage(self):
        """Manifest must include the binary itself; otherwise RuntimeError."""
        engine = s.Engine('/b', '/m', '/r', 'a' * 64)
        # Manifest covers only a dylib, not the binary.
        manifest = {'files': {
            'libfoo.dylib': {'sha256': 'c' * 64, 'bytes': 1000},
        }}
        with (patch.object(s, 'digest_file', side_effect=['a' * 64, 'c' * 64]),
              patch.object(Path, 'read_bytes', return_value=json.dumps(manifest).encode()),
              patch.object(s, 'checked_path', side_effect=lambda r, n: r / n),
              patch.object(Path, 'stat', return_value=SimpleNamespace(st_size=1000))):
            # Binary resolve won't match any manifest entry.
            with patch.object(Path, 'resolve', side_effect=lambda strict=False:
                              Path('/different/binary') if str(engine.binary) == '/b' else Path('/b').parent.resolve() / 'libfoo.dylib'):
                with self.assertRaisesRegex(RuntimeError, 'does not cover the binary'):
                    engine.verify_runtime_manifest(lambda: None)

    def test_runtime_manifest_entry_must_have_sha256_and_bytes(self):
        """Each manifest entry must be {sha256: str, bytes: int}."""
        engine = s.Engine('/b', '/m', '/r', 'a' * 64)
        for bad_entry in ('just_a_hash', {'sha256': 'c' * 64}, {'bytes': 100}):
            manifest = {'files': {'llama-b11459': bad_entry}}
            with (patch.object(s, 'digest_file', return_value='a' * 64),
                  patch.object(Path, 'read_bytes', return_value=json.dumps(manifest).encode())):
                with self.assertRaises(RuntimeError):
                    engine.verify_runtime_manifest(lambda: None)

    def test_runtime_manifest_file_size_drift(self):
        """Manifest entry byte count must match actual file size."""
        engine = s.Engine('/b', '/m', '/r', 'a' * 64)
        manifest = {'files': {'llama-b11459': {'sha256': 'c' * 64, 'bytes': 999}}}
        with (patch.object(s, 'digest_file', side_effect=['a' * 64, 'c' * 64]),
              patch.object(Path, 'read_bytes', return_value=json.dumps(manifest).encode()),
              patch.object(s, 'checked_path', side_effect=lambda r, n: r / n),
              patch.object(Path, 'stat', return_value=SimpleNamespace(st_size=1000))):
            with self.assertRaisesRegex(RuntimeError, 'size drift'):
                engine.verify_runtime_manifest(lambda: None)

    def test_runtime_manifest_empty_files(self):
        engine = s.Engine('/b', '/m', '/r', 'a' * 64)
        manifest = {'files': {}}
        with patch.object(s, 'digest_file', return_value='a' * 64):
            with patch.object(Path, 'read_bytes', return_value=json.dumps(manifest).encode()):
                with self.assertRaises(RuntimeError):
                    engine.verify_runtime_manifest(lambda: None)

    def test_runtime_manifest_root_is_binary_parent_not_home(self):
        """Root for manifest resolution must be binary.parent, not Path.home()."""
        import inspect
        source = inspect.getsource(s.Engine.verify_runtime_manifest)
        self.assertNotIn('Path.home()', source)
        self.assertNotIn('home', source.split('root')[0])
        # Root is set from self.binary.parent.resolve()
        self.assertIn('self.binary.parent', source)


class LlamaApiTests(unittest.TestCase):
    """(3) llama_api must use no-proxy no-redirect opener with bounded read."""

    def test_no_redirect_on_301(self):
        """Redirects must be rejected, not followed."""
        # The opener uses _NoRedirect which raises HTTPError on redirect.
        import urllib.error
        with patch.object(s._opener, 'open', side_effect=urllib.error.HTTPError(
                'http://evil/', 301, 'Redirect', {}, None)):
            with self.assertRaises(urllib.error.HTTPError):
                s.llama_api(54321, '/health')

    def test_bounded_read_rejects_oversized_response(self):
        """Response larger than 512 KiB must be rejected."""
        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = b'x' * (s.MAX_JSON_RESPONSE + 1)
        with patch.object(s._opener, 'open', return_value=mock_response):
            with self.assertRaisesRegex(RuntimeError, '512 KiB'):
                s.llama_api(54321, '/health')

    def test_bounded_read_accepts_normal_response(self):
        """Normal-sized response must be accepted."""
        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = json.dumps({'status': 'ok'}).encode()
        with patch.object(s._opener, 'open', return_value=mock_response):
            result = s.llama_api(54321, '/health')
            self.assertEqual(result, {'status': 'ok'})

    def test_max_json_response_constant(self):
        self.assertEqual(s.MAX_JSON_RESPONSE, 512 * 1024)

    def test_opener_disables_proxies(self):
        """Opener must be configured to disable proxies (ProxyHandler({}))."""
        # When ProxyHandler({}) is passed, no proxy handler with actual proxies
        # should be in the chain. Verify no handler has proxies set.
        for h in s._opener.handlers:
            if hasattr(h, 'proxies'):
                self.assertEqual(h.proxies, {},
                                 f'{type(h).__name__} has proxies: {h.proxies}')


class PropsValidationTests(unittest.TestCase):
    """(6) verify props: model_alias, model_path, single choice, output str, finite tokens."""

    def test_props_missing_model_alias_raises(self):
        """Props without model_alias matching MODEL_ID must raise."""
        engine = s.Engine('/binary', '/model.gguf', '/runtime', 'a' * 64)
        engine.gguf_sha256 = s.GGUF_SHA256
        engine.gguf_stat = (s.GGUF_BYTES, 1, 2, 3, 4)

        bad_props = make_props(model_alias='wrong-alias')

        tokens = [2, 100, 200]
        rendered = '<|turn>system\ntest<turn|>\n<|turn>user\ntest<turn|>\n<|turn>model\n'

        def mock_api(port, endpoint, body=None, timeout=8):
            if endpoint == '/health':
                return {'status': 'ok'}
            elif endpoint == '/props':
                return bad_props
            raise RuntimeError(f'Unexpected: {endpoint}')

        with (patch.object(s.Engine, 'verify_stat_identity'),
              patch.object(s.Engine, 'verify_runtime_manifest'),
              patch.object(Path, 'open', return_value=MagicMock()),
              patch.object(s.fcntl, 'flock'),
              patch.object(s, 'memory', return_value={'available_GiB': 8, 'swap_GiB': 1}),
              patch.object(s.time, 'monotonic', return_value=0),
              patch.object(s.time, 'time_ns', return_value=123456789),
              patch.object(s.socket, 'socket') as mock_sock,
              patch.object(s.subprocess, 'Popen') as mock_popen,
              patch.object(s.os, 'killpg'),
              patch.object(s, 'llama_api', side_effect=mock_api),
              patch.object(s.hashlib, 'sha256') as mock_sha,
              patch.object(s, 'resource_check')):
            mock_sock.return_value.__enter__ = MagicMock(return_value=mock_sock.return_value)
            mock_sock.return_value.__exit__ = MagicMock(return_value=False)
            mock_sock.return_value.getsockname.return_value = ('127.0.0.1', 54321)
            proc = MagicMock()
            proc.pid = 12345
            proc.poll.side_effect = iter([None, 0, 0])
            mock_popen.return_value = proc
            mock_sha.return_value.hexdigest.return_value = s.TEMPLATE_SHA256
            s._shutdown = False
            with self.assertRaisesRegex(RuntimeError, 'model_alias'):
                engine.infer(request())

    def test_props_missing_model_path_raises(self):
        """Props without model_path string must raise."""
        engine = s.Engine('/binary', '/model.gguf', '/runtime', 'a' * 64)
        engine.gguf_sha256 = s.GGUF_SHA256
        engine.gguf_stat = (s.GGUF_BYTES, 1, 2, 3, 4)

        bad_props = make_props()
        del bad_props['model_path']

        def mock_api(port, endpoint, body=None, timeout=8):
            if endpoint == '/health':
                return {'status': 'ok'}
            elif endpoint == '/props':
                return bad_props
            raise RuntimeError(f'Unexpected: {endpoint}')

        with (patch.object(s.Engine, 'verify_stat_identity'),
              patch.object(s.Engine, 'verify_runtime_manifest'),
              patch.object(Path, 'open', return_value=MagicMock()),
              patch.object(s.fcntl, 'flock'),
              patch.object(s, 'memory', return_value={'available_GiB': 8, 'swap_GiB': 1}),
              patch.object(s.time, 'monotonic', return_value=0),
              patch.object(s.time, 'time_ns', return_value=123456789),
              patch.object(s.socket, 'socket') as mock_sock,
              patch.object(s.subprocess, 'Popen') as mock_popen,
              patch.object(s.os, 'killpg'),
              patch.object(s, 'llama_api', side_effect=mock_api),
              patch.object(s.hashlib, 'sha256') as mock_sha,
              patch.object(s, 'resource_check')):
            mock_sock.return_value.__enter__ = MagicMock(return_value=mock_sock.return_value)
            mock_sock.return_value.__exit__ = MagicMock(return_value=False)
            mock_sock.return_value.getsockname.return_value = ('127.0.0.1', 54321)
            proc = MagicMock()
            proc.pid = 12345
            proc.poll.side_effect = iter([None, 0, 0])
            mock_popen.return_value = proc
            mock_sha.return_value.hexdigest.return_value = s.TEMPLATE_SHA256
            s._shutdown = False
            with self.assertRaisesRegex(RuntimeError, 'model_path'):
                engine.infer(request())


class SocketFramingTests(unittest.TestCase):
    """(7) Socket framing: duplicate TE/get_all, bound."""

    def handler(self, payload=None, method='POST', path='/v1/chat/completions',
                headers=None, raw=None):
        handler = object.__new__(s.Handler)
        handler.server = SimpleNamespace(
            token='a' * 32,
            engine=MagicMock(gguf_sha256='test_hash'),
        )
        handler.command, handler.path = method, path
        handler.headers = HTTPMessage()
        raw = (json.dumps(request() if payload is None else payload,
                          ensure_ascii=False).encode() if raw is None else raw)
        values = {'Authorization': 'Bearer ' + 'a' * 32,
                  'Content-Length': str(len(raw)),
                  'Content-Type': 'application/json'}
        values.update(headers or {})
        for name, value in values.items():
            if value is not None:
                handler.headers[name] = value
        handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
        handler.send_json = MagicMock()
        return handler

    def test_duplicate_transfer_encoding_rejected(self):
        """Duplicate Transfer-Encoding headers must be rejected."""
        h = self.handler()
        h.headers['Transfer-Encoding'] = 'chunked'
        h.headers['Transfer-Encoding'] = 'identity'  # adds second
        h.dispatch()
        self.assertEqual(h.send_json.call_args.args[0], 400)
        h.server.engine.infer.assert_not_called()

    def test_single_transfer_encoding_rejected(self):
        """Any Transfer-Encoding must be rejected (uses get_all)."""
        h = self.handler()
        h.headers['Transfer-Encoding'] = 'chunked'
        h.dispatch()
        self.assertEqual(h.send_json.call_args.args[0], 400)
        h.server.engine.infer.assert_not_called()

    def test_duplicate_content_length_rejected(self):
        """Duplicate Content-Length must be rejected."""
        h = self.handler()
        h.headers['Content-Length'] = '100'  # adds a second one
        h.dispatch()
        self.assertEqual(h.send_json.call_args.args[0], 400)
        h.server.engine.infer.assert_not_called()


class CLITests(unittest.TestCase):
    def setUp(self):
        s._shutdown = False

    def tearDown(self):
        s._shutdown = False

    def argv(self):
        return ['bolt_service.py', '--host', '100.100.100.100',
                '--binary-path', '/binary', '--model-path', '/model.gguf',
                '--runtime-manifest', '/runtime',
                '--runtime-manifest-sha256', 'a' * 64,
                '--token-file', '/token']

    def test_cli_uses_serial_server_and_closes(self):
        with (patch.object(s.sys, 'argv', self.argv()),
              patch.object(Path, 'read_text', return_value='a' * 32),
              patch.object(s, 'Engine') as engine,
              patch.object(s, 'Server') as server,
              patch.object(s.signal, 'signal')):
            engine.return_value.verify_startup = MagicMock()
            s._shutdown = True  # exit serve loop immediately
            s.main()
            server.assert_called_once_with(('100.100.100.100', 8094), s.Handler)
            engine.assert_called_once_with(Path('/binary'), Path('/model.gguf'),
                                           Path('/runtime'), 'a' * 64, 18.0)
            engine.return_value.verify_startup.assert_called_once()
            server.return_value.server_close.assert_called_once()

    def test_cli_rejects_non_tailnet_or_bad_token(self):
        for host, token in (
            ('0.0.0.0', 'a' * 32), ('127.0.0.1', 'a' * 32),
            ('100.100.100.100', 'short'), ('100.100.100.100', 'a' * 32 + ' secret'),
        ):
            argv = self.argv()
            argv[2] = host
            with (self.subTest(host=host, token_length=len(token)),
                  patch.object(s.sys, 'argv', argv),
                  patch.object(Path, 'read_text', return_value=token),
                  patch.object(s, 'Server') as server,
                  patch('sys.stderr', new_callable=io.StringIO)):
                with self.assertRaises(SystemExit):
                    s.main()
                server.assert_not_called()

    def test_default_port_is_8094(self):
        argv = self.argv()
        with (patch.object(s.sys, 'argv', argv),
              patch.object(Path, 'read_text', return_value='a' * 32),
              patch.object(s, 'Engine') as engine,
              patch.object(s, 'Server') as server,
              patch.object(s.signal, 'signal')):
            engine.return_value.verify_startup = MagicMock()
            s._shutdown = True
            s.main()
            self.assertEqual(server.call_args[0][0][1], 8094)

    def test_signal_handlers_installed(self):
        signals_set = []
        with (patch.object(s.sys, 'argv', self.argv()),
              patch.object(Path, 'read_text', return_value='a' * 32),
              patch.object(s, 'Engine') as engine,
              patch.object(s, 'Server') as server,
              patch.object(s.signal, 'signal', side_effect=lambda sig, handler: signals_set.append(sig))):
            engine.return_value.verify_startup = MagicMock()
            s._shutdown = True
            s.main()
            self.assertIn(signal.SIGTERM, signals_set)
            self.assertIn(signal.SIGHUP, signals_set)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        s._shutdown = False

    def tearDown(self):
        s._shutdown = False

    def handler(self, payload=None, method='POST', path='/v1/chat/completions',
                headers=None, raw=None):
        handler = object.__new__(s.Handler)
        handler.server = SimpleNamespace(
            token='a' * 32,
            engine=MagicMock(gguf_sha256='test_hash'),
        )
        handler.command, handler.path = method, path
        handler.headers = HTTPMessage()
        raw = (json.dumps(request() if payload is None else payload,
                          ensure_ascii=False).encode() if raw is None else raw)
        values = {'Authorization': 'Bearer ' + 'a' * 32,
                  'Content-Length': str(len(raw)),
                  'Content-Type': 'application/json'}
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
        # Duplicate auth header.
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

    def test_health_reports_loaded_false(self):
        h = self.handler(method='GET', path='/health')
        h.dispatch()
        result = h.send_json.call_args.args[1]
        self.assertFalse(result['loaded'])
        self.assertEqual(result['model'], s.MODEL_ID)
        self.assertEqual(result['gguf_sha256'], 'test_hash')

    def test_paths_and_methods(self):
        for method, path, status in (
            ('POST', '/bad', 404), ('GET', '/v1/chat/completions', 405),
            ('PUT', '/health', 405), ('GET', '/health?x', 404),
        ):
            h = self.handler(method=method, path=path)
            h.dispatch()
            self.assertEqual(h.send_json.call_args.args[0], status)
            h.server.engine.infer.assert_not_called()

    def test_body_rejections(self):
        for headers, raw in (
            ({'Content-Length': '0'}, b''),
            ({'Content-Length': str(s.MAX_BODY + 1)}, b''),
            ({'Content-Length': '2'}, b'{'),
            ({'Content-Length': None}, b''),
            ({'Content-Length': '+2'}, b'{}'),
            ({'Transfer-Encoding': 'chunked'}, b'{}'),
            ({'Content-Type': 'text/plain'}, b'{}'),
            ({}, b'\xff'),
            ({}, b'{'),
            ({}, b'{"x": NaN}'),
            ({}, b'{"x": 1, "x": 2}'),
        ):
            h = self.handler(headers=headers, raw=raw)
            h.dispatch()
            self.assertEqual(h.send_json.call_args.args[0], 400)
            h.server.engine.infer.assert_not_called()
        # Body shorter than Content-Length.
        h = self.handler()
        h.headers['Content-Length'] = '1'
        h.dispatch()
        self.assertEqual(h.send_json.call_args.args[0], 400)

    def test_errors_sanitized_no_content_leak(self):
        for error, status in (
            (ValueError('secret transcript'), 400),
            (MemoryError('secret path'), 503),
            (TimeoutError('secret token'), 503),
        ):
            h = self.handler()
            h.server.engine.infer.side_effect = error
            h.dispatch()
            self.assertEqual(h.send_json.call_args.args[0], status)
            self.assertNotIn('secret', str(h.send_json.call_args))
            h.server.engine.infer.assert_called_once()

    def test_service_shutdown_returns_503(self):
        """ServiceShutdown (BaseException) must be caught by handler and return 503."""
        h = self.handler()
        h.server.engine.infer.side_effect = s.ServiceShutdown('shutting down')
        h.dispatch()
        self.assertEqual(h.send_json.call_args.args[0], 503)

    def test_success_passes_exact_payload_and_result(self):
        h = self.handler()
        h.server.engine.infer.return_value = {'content': '  сырой\r\n'}
        h.dispatch()
        h.server.engine.infer.assert_called_once_with(request())
        h.send_json.assert_called_once_with(200, {'content': '  сырой\r\n'})

    def test_socket_timeout(self):
        import subprocess
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

    def test_duplicate_json_key_rejected(self):
        h = self.handler(raw=b'{"x": 1, "x": 2}')
        h.dispatch()
        self.assertEqual(h.send_json.call_args.args[0], 400)

    def test_nan_json_rejected(self):
        h = self.handler(raw=b'{"x": NaN}')
        h.dispatch()
        self.assertEqual(h.send_json.call_args.args[0], 400)

    def test_shutdown_flag_rejects_requests(self):
        """When _shutdown is set, handler returns 503 without calling infer."""
        s._shutdown = True
        h = self.handler()
        h.dispatch()
        self.assertEqual(h.send_json.call_args.args[0], 503)
        h.server.engine.infer.assert_not_called()


class OptimizedPythonTests(unittest.TestCase):
    """Verify key checks do not rely on assert statements (-O safe)."""

    def test_parse_request_uses_raise_not_assert(self):
        with self.assertRaises(ValueError):
            s.parse_request(None)
        with self.assertRaises(ValueError):
            s.parse_request({'model': 'wrong'})

    def test_resource_check_uses_raise_not_assert(self):
        with self.assertRaises(MemoryError):
            s.resource_check({'available_GiB': 1, 'swap_GiB': 0}, 0, admission=True)

    def test_validate_template_uses_raise_not_assert(self):
        with self.assertRaises(RuntimeError):
            s.validate_template('wrong', 'sys', 'usr', [2, 1])


class DeadlineCleanupTests(unittest.TestCase):
    """Actual deadline 18s must INCLUDE cleanup; work stops at 13s, cleanup gets margin."""

    def test_work_deadline_less_than_total(self):
        engine = s.Engine('/b', '/m', '/r', 'a' * 64, 18)
        self.assertLess(engine.work_deadline, engine.deadline_seconds)
        self.assertEqual(engine.work_deadline, 18 - s.CLEANUP_MARGIN)

    def test_cleanup_margin_constant(self):
        self.assertEqual(s.CLEANUP_MARGIN, 5)
        self.assertEqual(s.WORK_DEADLINE, 13)

    def test_total_seconds_includes_cleanup(self):
        """total_seconds in result must be measured after cleanup, not before."""
        import inspect
        source = inspect.getsource(s.Engine.infer)
        # Find the line that sets total_seconds.
        lines = source.split('\n')
        total_seconds_line = None
        lock_close_line = None
        for i, line in enumerate(lines):
            if 'total_seconds' in line and 'monotonic' in line:
                total_seconds_line = i
            if 'lock.close()' in line and lock_close_line is None:
                lock_close_line = i
        self.assertIsNotNone(total_seconds_line)
        self.assertIsNotNone(lock_close_line)
        # total_seconds must be measured AFTER lock.close() (cleanup).
        self.assertGreater(total_seconds_line, lock_close_line)


if __name__ == '__main__':
    unittest.main()
