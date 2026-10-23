"""FrogNano selection reuses the existing bounded transport and lexical guards."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bonsai_normalizer import (
    BonsaiNormalizer, BonsaiNormalizerConfig, DEFAULT_MODEL, DEFAULT_REVISION, SYSTEM_PROMPT,
)
from frognano_normalizer import (
    FrogNanoNormalizer, FrogNanoNormalizerConfig, FROGNANO_MODEL, FROGNANO_REVISION,
    FROGNANO_SYSTEM_PROMPT, get_frognano_normalizer,
)


def config(**updates):
    return FrogNanoNormalizerConfig.from_dict({
        'model': FROGNANO_MODEL, 'revision': FROGNANO_REVISION,
        'token': 'synthetic-test-token', **updates,
    })


def response(content, revision=FROGNANO_REVISION, finish='stop'):
    result = MagicMock()
    result.__enter__.return_value = result
    result.read.return_value = json.dumps({
        'model': FROGNANO_MODEL, 'revision': revision,
        'choices': [{'finish_reason': finish, 'message': {'content': content}}],
    }).encode()
    return result


class FrogNanoClient(unittest.TestCase):
    def test_prompt_matches_fixed_service_and_covers_missed_forms(self):
        import ast
        service = Path(__file__).resolve().parents[2] / 'frognano-stt/frognano_service.py'
        tree = ast.parse(service.read_text())
        prompt = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'SYSTEM_PROMPT' for t in n.targets))
        self.assertEqual(prompt, FROGNANO_SYSTEM_PROMPT)
        for marker in ('блядь', 'блять', 'нахуй', 'ебаный', 'повторы', 'Внутри кавычек', 'копируй их точно'):
            self.assertIn(marker, prompt)

    def test_exact_identity_and_profile_only(self):
        cfg = config()
        self.assertEqual(cfg.max_tokens, 512)
        for updates in ({'revision': DEFAULT_REVISION}, {'model': DEFAULT_MODEL},
                        {'max_tokens': 513}, {'top_p': 1.0}, {'seed': 43},
                        {'presence_penalty': 0.1}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                config(**updates)
        self.assertEqual(BonsaiNormalizerConfig().model, DEFAULT_MODEL)
        self.assertEqual(BonsaiNormalizer()._messages_for_source('Текст.')[0]['content'], SYSTEM_PROMPT)

    @patch('urllib.request.OpenerDirector.open')
    def test_fixed_prompt_and_exact_success_without_repair(self, opened):
        source = 'Ох, сохрани отчёт 29.\r\n\tНе меняй имя.  '
        candidate = 'сохрани отчёт 29.\r\n\tНе меняй имя.  '
        opened.return_value = response(candidate)
        text, meta = FrogNanoNormalizer(config()).normalize(source)
        self.assertEqual(text.encode(), candidate.encode())
        self.assertEqual(meta['status'], 'applied')
        self.assertEqual(meta['model'], FROGNANO_MODEL)
        opened.assert_called_once()
        payload = json.loads(opened.call_args.args[0].data)
        self.assertEqual(payload['messages'], [
            {'role': 'system', 'content': FROGNANO_SYSTEM_PROMPT},
            {'role': 'user', 'content': source},
        ])
        self.assertEqual(payload['max_tokens'], 512)
        self.assertEqual(payload['temperature'], 0.0)
        self.assertEqual(payload['seed'], 42)

    @patch('urllib.request.OpenerDirector.open')
    def test_protocol_identity_incomplete_and_lexical_failure_preserve_exact_input(self, opened):
        source = 'Не меняй порт 9417, если копия не готова.  \r\n\t'
        cases = [
            response(source, revision=DEFAULT_REVISION),
            response(source, finish='length'),
            response('<think>мысли</think>' + source),
            response('Ответ: ' + source),
            response('Меняй порт 9417, если копия не готова.'),
            response('Не меняй порт 9418, если копия не готова.'),
        ]
        for item in cases:
            with self.subTest(body=item.read.return_value):
                opened.reset_mock()
                opened.return_value = item
                text, meta = FrogNanoNormalizer(config()).normalize(source)
                self.assertEqual(text.encode(), source.encode())
                self.assertEqual(meta['status'], 'fallback')
                opened.assert_called_once()

    @patch('urllib.request.OpenerDirector.open', side_effect=TimeoutError('private test payload'))
    def test_timeout_exact_fallback_no_retry(self, opened):
        source = 'Исправленный вход.\r\n\t  '
        text, meta = FrogNanoNormalizer(config()).normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['reason'], 'timeout')
        self.assertNotIn('private test payload', json.dumps(meta))
        opened.assert_called_once()

    def test_factory_selects_only_explicit_pinned_config(self):
        body = json.dumps({'model': FROGNANO_MODEL, 'revision': FROGNANO_REVISION})
        from unittest.mock import mock_open
        with patch('os.path.isfile', return_value=True), patch('builtins.open', mock_open(read_data=body)):
            normalizer = get_frognano_normalizer('synthetic.json')
        self.assertEqual(normalizer.model, FROGNANO_MODEL)
        self.assertEqual(normalizer.revision, FROGNANO_REVISION)
        self.assertEqual(normalizer.config.max_tokens, 512)


if __name__ == '__main__':
    unittest.main()
