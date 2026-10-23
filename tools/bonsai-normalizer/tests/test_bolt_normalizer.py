"""Comprehensive unit tests for Bolt smart editor normalizer client.

Validates: identity/model/revision/EOS/timeout, exact sampler, one call/no retry,
protocol leak rejection, source alignment, quote/instruction/negation/condition/number
preservation, empty output rejection, unchanged no-op, repeated/source alignment,
exact whitespace bytes.  No remote calls, SSH, inference, private/audio access.
"""
from __future__ import annotations

import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, mock_open, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bonsai_normalizer import (
    BonsaiNormalizerConfig, DEFAULT_MODEL, DEFAULT_REVISION, SYSTEM_PROMPT,
)
from bolt_normalizer import (
    BOLT_MODEL, BOLT_REVISION, BOLT_SYSTEM_PROMPT,
    BoltNormalizer, BoltNormalizerConfig, get_bolt_normalizer,
)


def _make_response(content, model=BOLT_MODEL, revision=BOLT_REVISION,
                   finish='stop', **extra):
    data = {
        'model': model, 'revision': revision,
        'choices': [{'finish_reason': finish,
                     'message': {'role': 'assistant', 'content': content}}],
        **extra,
    }
    result = MagicMock()
    result.__enter__.return_value = result
    result.read.return_value = json.dumps(data).encode()
    return result


def _config(**updates):
    return BoltNormalizerConfig.from_dict({
        'model': BOLT_MODEL, 'revision': BOLT_REVISION, **updates,
    })


class TestBoltNormalizerConfig(unittest.TestCase):
    """Pinned identity, max_tokens=512, exact sampler profile."""

    def test_default_config(self):
        cfg = BoltNormalizerConfig()
        self.assertEqual(cfg.model, BOLT_MODEL)
        self.assertEqual(cfg.revision, BOLT_REVISION)
        self.assertEqual(cfg.max_tokens, 512)
        self.assertEqual(cfg.temperature, 0.0)
        self.assertEqual(cfg.seed, 42)
        self.assertEqual(cfg.top_p, 0.8)
        self.assertEqual(cfg.top_k, 20)
        self.assertEqual(cfg.min_p, 0.0)
        self.assertEqual(cfg.presence_penalty, 0.0)
        self.assertEqual(cfg.repetition_penalty, 1.0)
        self.assertTrue(cfg.enabled)

    def test_exact_identity_rejects_wrong_model_or_revision(self):
        for updates in (
            {'model': DEFAULT_MODEL},
            {'revision': DEFAULT_REVISION},
            {'model': 'other-model'},
            {'revision': ''},
            {'revision': 'aaaa'},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                _config(**updates)

    def test_max_tokens_limited_to_512(self):
        for bad in (513, 1024, 0, -1, True, 1.0):
            with self.subTest(val=bad), self.assertRaises(ValueError):
                _config(max_tokens=bad)
        cfg = _config(max_tokens=256)
        self.assertEqual(cfg.max_tokens, 256)

    def test_exact_sampler_profile_required(self):
        for updates in (
            {'temperature': 0.7}, {'seed': 43}, {'top_p': 1.0},
            {'presence_penalty': 0.1}, {'repetition_penalty': 0.5},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                _config(**updates)

    def test_shared_transport_bounds_from_parent(self):
        for updates in (
            {'timeout_seconds': math.inf},
            {'max_timeout_seconds': math.nan},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                _config(**updates)

    def test_from_dict_rejects_extra_keys(self):
        with self.assertRaises(ValueError):
            BoltNormalizerConfig.from_dict({'model': BOLT_MODEL, 'extra_field': True})

    def test_bonsai_config_remains_independent(self):
        # Bonsai default must still use its own model/revision.
        bonsai = BonsaiNormalizerConfig()
        self.assertEqual(bonsai.model, DEFAULT_MODEL)
        self.assertEqual(bonsai.revision, DEFAULT_REVISION)
        self.assertNotEqual(bonsai.model, BOLT_MODEL)


class TestBoltNormalizerClient(unittest.TestCase):
    """Fixed prompt, pinned identity, one-call, exact sampler in payload."""

    @patch('urllib.request.OpenerDirector.open')
    def test_fixed_prompt_and_exact_payload(self, opened):
        source = 'Проверь отчёт 29. Не меняй имя.'
        # Model returns exactly source (no-op) — no cleanup needed
        opened.return_value = _make_response(source)
        text, meta = BoltNormalizer(_config()).normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['status'], 'unchanged')
        self.assertEqual(meta['model'], BOLT_MODEL)

        opened.assert_called_once()
        payload = json.loads(opened.call_args.args[0].data)
        self.assertEqual(payload['messages'], [
            {'role': 'system', 'content': BOLT_SYSTEM_PROMPT},
            {'role': 'user', 'content': source},
        ])
        self.assertEqual(payload['max_tokens'], 512)
        self.assertEqual(payload['temperature'], 0.0)
        self.assertEqual(payload['seed'], 42)
        self.assertEqual(payload['top_p'], 0.8)
        self.assertEqual(payload['top_k'], 20)
        self.assertEqual(payload['min_p'], 0.0)
        self.assertEqual(payload['presence_penalty'], 0.0)
        self.assertEqual(payload['repetition_penalty'], 1.0)
        self.assertFalse(payload['stream'])

    @patch('urllib.request.OpenerDirector.open')
    def test_system_prompt_is_fixed_frognano_not_bonsai(self, opened):
        self.assertNotEqual(BOLT_SYSTEM_PROMPT, SYSTEM_PROMPT)
        self.assertIn('Ты редактор русской диктовки', BOLT_SYSTEM_PROMPT)
        self.assertIn('отрицания', BOLT_SYSTEM_PROMPT)
        self.assertIn('кавычек', BOLT_SYSTEM_PROMPT)

    @patch('urllib.request.OpenerDirector.open')
    def test_successful_profanity_removal(self, opened):
        source = 'Блять, проверь журнал 56.'
        opened.return_value = _make_response('проверь журнал 56.')
        text, meta = BoltNormalizer().normalize(source)
        self.assertEqual(text, 'проверь журнал 56.')
        self.assertEqual(meta['status'], 'applied')
        self.assertGreater(meta['latency_ms'], 0.0)
        opened.assert_called_once()

    @patch('urllib.request.OpenerDirector.open')
    def test_exact_whitespace_bytes_preserved(self, opened):
        source = 'Блять, сохрани /tmp/a\t  и 42.\r\nНе меняй «А  Б».  '
        opened.return_value = _make_response(source.removeprefix('Блять, '))
        text, _ = BoltNormalizer().normalize(source)
        self.assertEqual(text.encode(), source.removeprefix('Блять, ').encode())


class TestBoltProtocolFailures(unittest.TestCase):
    """Model/revision/EOS/timeout, one call, no retry."""

    @patch('urllib.request.OpenerDirector.open')
    def test_strict_bolt_decoder_rejects_ambiguous_or_reasoning_response(self, opened):
        source = 'Не меняй порт 4628.'
        responses = [
            ('{"model":"wrong","model":' + json.dumps(BOLT_MODEL) + ',"choices":[]}').encode(),
            b'{"choices":[],"extra":NaN}',
            json.dumps({'model': BOLT_MODEL, 'revision': BOLT_REVISION,
                        'choices': [{'message': {'content': source}, 'finish_reason': 'stop'}] * 2}).encode(),
            json.dumps({'model': BOLT_MODEL, 'revision': BOLT_REVISION,
                        'choices': [{'message': {'content': source, 'reasoning_content': 'hidden'},
                                     'finish_reason': 'stop'}]}).encode(),
        ]
        for raw in responses:
            response = MagicMock()
            response.__enter__.return_value = response
            response.read.return_value = raw
            opened.return_value = response
            text, meta = BoltNormalizer().normalize(source)
            self.assertEqual(text, source)
            self.assertEqual(meta['status'], 'fallback')


    @patch('urllib.request.OpenerDirector.open')
    def test_oversized_bolt_response_preserves_shared_size_guard(self, opened):
        source = 'Не меняй порт 4628.'
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'x' * (64 * 1024 + 1)
        opened.return_value = response
        text, meta = BoltNormalizer().normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['reason'], 'response_too_large')
        opened.assert_called_once()

    @patch('urllib.request.OpenerDirector.open')
    def test_model_mismatch_returns_source(self, opened):
        source = 'проверь статус'
        opened.return_value = _make_response(source, model='wrong-model')
        text, meta = BoltNormalizer().normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['status'], 'fallback')
        self.assertEqual(meta['reason'], 'model_mismatch')

    @patch('urllib.request.OpenerDirector.open')
    def test_revision_mismatch_returns_source(self, opened):
        source = 'проверь статус'
        opened.return_value = _make_response(source, revision='0' * 40)
        text, meta = BoltNormalizer().normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['status'], 'fallback')
        self.assertEqual(meta['reason'], 'revision_mismatch')

    @patch('urllib.request.OpenerDirector.open')
    def test_finish_reason_length_returns_source(self, opened):
        source = 'проверь статус'
        opened.return_value = _make_response(source, finish='length')
        text, meta = BoltNormalizer().normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['status'], 'fallback')
        self.assertEqual(meta['reason'], 'finish_reason_length')

    @patch('urllib.request.OpenerDirector.open')
    def test_timeout_returns_source_no_retry(self, opened):
        opened.side_effect = TimeoutError('timed out')
        source = 'проверь статус'
        text, meta = BoltNormalizer().normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['reason'], 'timeout')
        opened.assert_called_once()

    @patch('urllib.request.OpenerDirector.open')
    def test_empty_candidate_returns_source(self, opened):
        source = 'проверь статус'
        opened.return_value = _make_response('   ')
        text, meta = BoltNormalizer().normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['status'], 'fallback')
        self.assertEqual(meta['reason'], 'empty_candidate')

    @patch('urllib.request.OpenerDirector.open')
    def test_protocol_leak_think_tags_rejected(self, opened):
        source = 'Блять, проверь статус.'
        opened.return_value = _make_response('<think>мысли</think>' + source)
        text, meta = BoltNormalizer().normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['status'], 'fallback')

    @patch('urllib.request.OpenerDirector.open')
    def test_protocol_leak_preamble_rejected(self, opened):
        source = 'Блять, проверь статус.'
        opened.return_value = _make_response('Ответ: проверь статус.')
        text, meta = BoltNormalizer().normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['status'], 'fallback')

    @patch('urllib.request.OpenerDirector.open')
    def test_protocol_leak_codeblock_rejected(self, opened):
        source = 'Блять, проверь статус.'
        opened.return_value = _make_response('```\nпроверь статус.\n```')
        text, meta = BoltNormalizer().normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['status'], 'fallback')

    @patch('urllib.request.OpenerDirector.open')
    def test_finish_reason_does_not_leak_content(self, opened):
        secret = 'private transcript and secret_token'
        opened.return_value = _make_response('текст', finish=secret)
        with patch('sys.stdout', new_callable=io.StringIO) as output:
            text, meta = BoltNormalizer().normalize('проверь статус')
        self.assertEqual(text, 'проверь статус')
        self.assertEqual(meta['reason'], 'finish_reason_invalid')
        self.assertNotIn(secret, json.dumps(meta) + output.getvalue())


class TestBoltValidationGuards(unittest.TestCase):
    """Shared lexical guards run before the stronger finite deletion validator."""

    @patch('urllib.request.OpenerDirector.open')
    def test_negation_loss_rejected(self, opened):
        source = 'не удаляй файл конфигурации'
        opened.return_value = _make_response('Удаляй файл конфигурации.')
        text, meta = BoltNormalizer().normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['status'], 'fallback')
        self.assertEqual(meta['reason'], 'validation_negation_lost')

    @patch('urllib.request.OpenerDirector.open')
    def test_number_loss_rejected(self, opened):
        source = 'сервер на порту 8091 упал'
        opened.return_value = _make_response('Сервер на порту упал.')
        text, meta = BoltNormalizer().normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['reason'], 'validation_numeric_missing')

    @patch('urllib.request.OpenerDirector.open')
    def test_condition_loss_rejected(self, opened):
        source = 'Кажется, сервер не готов'
        opened.return_value = _make_response('Сервер не готов.')
        text, meta = BoltNormalizer().normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['reason'], 'validation_qualifier_lost')

    @patch('urllib.request.OpenerDirector.open')
    def test_latin_identifier_loss_rejected(self, opened):
        source = 'отправь отчет в Slack'
        opened.return_value = _make_response('Отправь отчет в мессенджер.')
        text, meta = BoltNormalizer().normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['reason'], 'validation_latin_missing')

    @patch('urllib.request.OpenerDirector.open')
    def test_instruction_word_order_change_rejected(self, opened):
        source = 'Сначала проверь логи, потом перезапусти сервер.'
        opened.return_value = _make_response(
            'Потом перезапусти сервер, сначала проверь логи.')
        text, meta = BoltNormalizer().normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['reason'], 'validation_word_order_changed')

    @patch('urllib.request.OpenerDirector.open')
    def test_model_deletes_substantive_content_unsupported(self, opened):
        source = 'Блять, проверь отчёт. Затем позвони Анне.'
        opened.return_value = _make_response('Проверь отчёт.')
        text, meta = BoltNormalizer().normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['status'], 'fallback')
        self.assertEqual(meta['reason'], 'validation_unsupported_edit')

    @patch('urllib.request.OpenerDirector.open')
    def test_repeated_numbers_guard(self, opened):
        source = 'открой 2 файла и еще 2 файла'
        opened.return_value = _make_response('Открой 2 файла.')
        text, meta = BoltNormalizer().normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['reason'], 'validation_numeric_missing')

    @patch('urllib.request.OpenerDirector.open')
    def test_negation_added_rejected(self, opened):
        source = 'сделай резервную копию'
        opened.return_value = _make_response('Не сделай резервную копию.')
        text, meta = BoltNormalizer().normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['reason'], 'validation_negation_added')


class TestBoltUnchangedNoOp(unittest.TestCase):
    """An unchanged valid model reply remains unchanged, no local forced cleanup."""

    @patch('urllib.request.OpenerDirector.open')
    def test_unchanged_clean_text_stays_unchanged(self, opened):
        source = 'Не меняй срок и endpoint.'
        opened.return_value = _make_response(source)
        text, meta = BoltNormalizer().normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['status'], 'unchanged')
        self.assertEqual(meta['reason'], 'no_supported_edit')

    @patch('urllib.request.OpenerDirector.open')
    def test_unchanged_status_explicit_no_op(self, opened):
        source = 'Проверь сервер и логи.'
        opened.return_value = _make_response(source)
        text, meta = BoltNormalizer().normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['status'], 'unchanged')

    @patch('urllib.request.OpenerDirector.open')
    def test_disabled_config_bypasses(self, opened):
        cfg = BoltNormalizerConfig(enabled=False)
        text, meta = BoltNormalizer(cfg).normalize('блять, текст')
        self.assertEqual(text, 'блять, текст')
        self.assertEqual(meta['status'], 'bypassed')
        opened.assert_not_called()


class TestBoltSourceAlignment(unittest.TestCase):
    """Source-aligned cleanup: output built from source slices, not model prose."""

    @patch('urllib.request.OpenerDirector.open')
    def test_source_alignment_comma_and_whitespace(self, opened):
        source = 'Да, блять, проверь это.'
        # Under the new contract: candidate is returned exactly (no local reconstruction).
        # Both comma variants are valid alternatives; each is returned as-is.
        for native, expected in [('Да, проверь это.', 'Да, проверь это.'),
                                 ('Да проверь это.', 'Да проверь это.')]:
            with self.subTest(native=native):
                opened.return_value = _make_response(native)
                text, meta = BoltNormalizer().normalize(source)
                self.assertEqual(text, expected)
                self.assertEqual(meta['status'], 'applied')

    @patch('urllib.request.OpenerDirector.open')
    def test_repeated_spans_bounded_and_occurrence_owned(self, opened):
        source = 'Блять, сохрани «блять». ' * 70
        opened.return_value = _make_response('сохрани «блять». ' * 70)
        text, meta = BoltNormalizer().normalize(source)
        self.assertEqual(text, 'сохрани «блять». ' * 70)
        self.assertEqual(meta['status'], 'applied')


class TestBoltFactoryAndEnv(unittest.TestCase):
    """Factory, env config, content-free errors."""

    def test_factory_selects_pinned_config(self):
        body = json.dumps({'model': BOLT_MODEL, 'revision': BOLT_REVISION})
        with patch('os.path.isfile', return_value=True), \
             patch('builtins.open', mock_open(read_data=body)):
            normalizer = get_bolt_normalizer('synthetic.json')
        self.assertEqual(normalizer.model, BOLT_MODEL)
        self.assertEqual(normalizer.revision, BOLT_REVISION)
        self.assertEqual(normalizer.config.max_tokens, 512)

    def test_factory_returns_none_for_missing_path(self):
        self.assertIsNone(get_bolt_normalizer(None))
        self.assertIsNone(get_bolt_normalizer('/nonexistent/bolt.json'))

    def test_factory_disabled_returns_none(self):
        body = json.dumps({
            'model': BOLT_MODEL, 'revision': BOLT_REVISION, 'enabled': False,
        })
        with patch('os.path.isfile', return_value=True), \
             patch('builtins.open', mock_open(read_data=body)):
            self.assertIsNone(get_bolt_normalizer('synthetic.json'))

    def test_factory_bad_config_content_free_error(self):
        body = json.dumps({'model': 'private transcript and token'})
        with patch('os.path.isfile', return_value=True), \
             patch('builtins.open', mock_open(read_data=body)), \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertIsNone(get_bolt_normalizer('synthetic.json'))
            self.assertIn('config_load_error', output.getvalue())
            self.assertNotIn('private transcript', output.getvalue())

    def test_env_var_factory(self):
        body = json.dumps({'model': BOLT_MODEL, 'revision': BOLT_REVISION})
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            f.write(body)
            path = f.name
        try:
            with patch.dict(os.environ, {'BOLT_NORMALIZER_CONFIG': path}):
                normalizer = get_bolt_normalizer()
                self.assertIsNotNone(normalizer)
                self.assertEqual(normalizer.model, BOLT_MODEL)
        finally:
            os.remove(path)

    def test_unset_env_returns_none(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(get_bolt_normalizer())


class TestBoltTokenAndAuth(unittest.TestCase):
    """Auth header, token secrecy, no content in error metadata."""

    @patch('urllib.request.OpenerDirector.open')
    def test_auth_header_and_timeout_cap(self, opened):
        token = 'private_bolt_token_xyz'
        source = 'private bolt transcript'
        normalizer = BoltNormalizer(BoltNormalizerConfig(
            token=token, timeout_seconds=25))
        opened.side_effect = TimeoutError()
        with patch('sys.stdout', new_callable=io.StringIO) as output:
            text, meta = normalizer.normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['reason'], 'timeout')
        self.assertNotIn(source, json.dumps(meta) + output.getvalue())
        self.assertNotIn(token, json.dumps(meta) + output.getvalue())
        req = opened.call_args.args[0]
        self.assertEqual(req.get_header('Authorization'), 'Bearer ' + token)
        self.assertEqual(opened.call_args.kwargs['timeout'], 20.0)
        opened.assert_called_once()


if __name__ == '__main__':
    unittest.main()
