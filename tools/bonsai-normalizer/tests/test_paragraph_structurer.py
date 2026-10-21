"""Finite model-free checks for insertion-only paragraph selection, not semantics."""
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import mock_open, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bonsai_normalizer import (
    BonsaiNormalizer, BonsaiNormalizerConfig, DEFAULT_MODEL, DEFAULT_REVISION,
    get_bonsai_normalizer,
)
from bonsai_paragraph_structurer import (
    BonsaiParagraphStructurer, PARAGRAPH_PROMPT, paragraph_boundaries, render_paragraphs,
)


def response(content, **overrides):
    data = {'model': DEFAULT_MODEL, 'revision': DEFAULT_REVISION,
            'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}
    data.update(overrides)
    return io.BytesIO(json.dumps(data).encode())


class TestParagraphStructurer(unittest.TestCase):
    SOURCE = 'Сохрани отчёт. Проверь копию. Позвони Анне.'

    def test_exact_boundary_offsets_and_insertion_without_strip(self):
        source = self.SOURCE + '\n\nХвост остаётся. Ещё одна мысль.  '
        spans = paragraph_boundaries(source)
        self.assertEqual(len(spans), 3)
        self.assertEqual([source[s['offset']:] for s in spans], [
            source[source.index('Проверь'):], source[source.index('Позвони'):],
            'Ещё одна мысль.  '])
        self.assertEqual(render_paragraphs(source, '{"break_after":[1]}'),
                         source.replace('Позвони', '\n\nПозвони'))
        self.assertEqual(render_paragraphs(source, '{"break_after":[]}'), source)
        self.assertEqual(render_paragraphs(source, '{"break_after":[0,1,2]}'),
                         source.replace('Проверь', '\n\nПроверь').replace(
                             'Позвони', '\n\nПозвони').replace('Ещё', '\n\nЕщё'))

    def test_all_source_bytes_and_existing_newlines_survive_exact_plan(self):
        for source in [self.SOURCE, 'Первый готов! Второй тоже? Третий… Четвёртый.',
                       'Ёлка готова. Новая мысль.\n\nУже есть абзац. Новый текст.',
                       'Сохрани 2 копии. Verify checksum. Потом сообщи Ольге.']:
            spans = paragraph_boundaries(source)
            for ids in ([], list(range(len(spans))), list(range(len(spans)))[::2]):
                result = render_paragraphs(source, json.dumps({'break_after': ids}))
                # Consume source bytes and only the exact declared insertions.
                expected = source.encode()
                for index in reversed(ids):
                    offset = len(source[:spans[index]['offset']].encode())
                    expected = expected[:offset] + b'\n\n' + expected[offset:]
                self.assertEqual(result.encode(), expected)

    def test_quotes_initials_abbreviations_and_existing_breaks_are_not_candidates(self):
        for source in ['Сохрани «Первая мысль. Вторая мысль».',
                       'Проф. Иванов приехал в г. Москву.', 'А. Иванов приехал.',
                       'Первый готов.\nВторой готов.', 'Первый готов; Второй готов.',
                       'Версия 1.2 готова.', 'Неполная «цитата. Дальше текст.',
                       'Первая мысль. вторая мысль.']:
            with self.subTest(source=source):
                self.assertEqual(paragraph_boundaries(source), [])
        source = 'Сохрани «Первая мысль. Вторая мысль». Проверь журнал.'
        self.assertEqual(paragraph_boundaries(source), [])  # closing quote is not guessed

    def test_technical_markup_and_controls_disable_whole_input(self):
        for marker in ['rm', 'echo', 'printf', 'bash', 'git', 'systemctl', 'путь',
                       '/ home / Анна', 'https://example.test', '`код`', 'код\\файл',
                       '# Header', '- item', '1. item', '> quote', '  indent',
                       'x=y', '$x', '[link]', '<tag>', '*emphasis*', '\r', '\t',
                       '\x00', '\x7f', '\u2028', '\u202e', 'условие && действие']:
            source = marker + '\n' + self.SOURCE
            with self.subTest(marker=marker):
                self.assertEqual(paragraph_boundaries(source), [])

    def test_bounded_inventory_and_no_shared_mutable_plan(self):
        self.assertEqual(len(paragraph_boundaries('Предложение готово. ' * 33)), 32)
        self.assertEqual(paragraph_boundaries('Предложение готово. ' * 34), [])
        plan = paragraph_boundaries(self.SOURCE)
        plan[0]['offset'] = 0
        self.assertGreater(paragraph_boundaries(self.SOURCE)[0]['offset'], 0)

    def test_strict_selection_json_never_repaired(self):
        invalid = ['', '{}', 'null', '[]', 'plain', '```json\n{"break_after":[0]}\n```',
                   '{"delete":[0]}', '{"break_after":[],"extra":1}',
                   '{"break_after":[],"break_after":[0]}', '{"break_after":true}',
                   '{"break_after":[true]}', '{"break_after":[0.0]}',
                   '{"break_after":["0"]}', '{"break_after":[-1]}',
                   '{"break_after":[2]}', '{"break_after":[0,0]}',
                   '{"break_after":[1,0]}', '{"break_after":[{}]}', '[' * 1500]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                render_paragraphs(self.SOURCE, value)

    @patch('urllib.request.OpenerDirector.open')
    def test_exact_transmission_and_no_deletion_schema(self, opened):
        editor = BonsaiParagraphStructurer()
        opened.return_value = response('{"break_after":[1]}')
        text, meta = editor.normalize(self.SOURCE)
        self.assertEqual(text, self.SOURCE.replace('Позвони', '\n\nПозвони'))
        self.assertEqual(meta['status'], 'applied')
        payload = json.loads(opened.call_args.args[0].data)
        self.assertNotIn('response_format', payload)
        self.assertEqual(payload['messages'][0]['content'], PARAGRAPH_PROMPT)
        self.assertEqual(json.loads(payload['messages'][1]['content']),
                         {'source': self.SOURCE, 'candidates': paragraph_boundaries(self.SOURCE)})
        self.assertEqual(payload['model'], DEFAULT_MODEL)
        self.assertEqual((payload['temperature'], payload['seed'], payload['stream']), (0.0, 42, False))
        opened.assert_called_once()

    @patch('urllib.request.OpenerDirector.open')
    def test_empty_selection_unchanged_invalid_selection_exact_fallback(self, opened):
        editor = BonsaiParagraphStructurer()
        for value, status, reason in [('{"break_after":[]}', 'unchanged', 'empty_paragraph_selection'),
                                      ('{"break_after":[99]}', 'fallback', 'invalid_edit_selection')]:
            with self.subTest(value=value):
                opened.return_value = response(value)
                text, meta = editor.normalize(self.SOURCE)
                self.assertEqual(text, self.SOURCE)
                self.assertEqual((meta['status'], meta['reason']), (status, reason))

    @patch('urllib.request.OpenerDirector.open')
    def test_unsupported_empty_disabled_and_bounds_never_contact_model(self, opened):
        editor = BonsaiParagraphStructurer()
        for source in ['', ' \n', 'Одна мысль.', 'cmd\n' + self.SOURCE]:
            self.assertEqual(editor.normalize(source)[0], source)
            self.assertEqual(editor.normalize(source)[1]['status'], 'bypassed')
        large = self.SOURCE * 200
        self.assertEqual(editor.normalize(large)[1]['reason'], 'input_length_exceeded')
        disabled = BonsaiParagraphStructurer(BonsaiNormalizerConfig(enabled=False))
        self.assertEqual(disabled.normalize(self.SOURCE)[1]['reason'], 'disabled_by_config')
        with patch.object(editor, '_messages_for_source', side_effect=ValueError('not logged')):
            self.assertEqual(editor.normalize(self.SOURCE)[1]['reason'], 'invalid_edit_plan')
        opened.assert_not_called()

    @patch('urllib.request.OpenerDirector.open')
    def test_identity_finish_encoding_and_transport_fallback(self, opened):
        editor = BonsaiParagraphStructurer()
        cases = [({'model': 'wrong'}, 'model_mismatch'),
                 ({'revision': 'wrong'}, 'revision_mismatch'),
                 ({'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]},
                  'finish_reason_length')]
        for override, reason in cases:
            opened.return_value = response('{"break_after":[0]}', **override)
            text, meta = editor.normalize(self.SOURCE)
            self.assertEqual(text, self.SOURCE)
            self.assertEqual(meta['reason'], reason)
        opened.return_value = response('\ud800')
        self.assertEqual(editor.normalize(self.SOURCE)[1]['reason'], 'invalid_content_encoding')
        opened.side_effect = TimeoutError('not logged')
        self.assertEqual(editor.normalize(self.SOURCE)[1]['reason'], 'timeout')

    def test_factory_remains_default_and_request_plans_are_concurrent_local(self):
        with patch('os.path.isfile', return_value=True), patch('builtins.open', mock_open(read_data='{}')):
            self.assertIs(type(get_bonsai_normalizer('unused')), BonsaiNormalizer)
        editor = BonsaiParagraphStructurer()
        state = editor.__dict__.copy()
        barrier = threading.Barrier(2)
        def opened(request, **_):
            data = json.loads(request.data)
            source = json.loads(data['messages'][1]['content'])['source']
            barrier.wait(timeout=3)
            return response(json.dumps({'break_after': [len(paragraph_boundaries(source)) - 1]}))
        sources = [self.SOURCE, self.SOURCE + ' Прочитай письмо.']
        with patch.object(editor._opener, 'open', side_effect=opened), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(editor.normalize, sources))
        for source, (text, meta) in zip(sources, results):
            self.assertEqual(text, render_paragraphs(source, json.dumps({
                'break_after': [len(paragraph_boundaries(source)) - 1]})))
            self.assertEqual(meta['status'], 'applied')
        self.assertEqual(editor.__dict__, state)


if __name__ == '__main__':
    unittest.main()
