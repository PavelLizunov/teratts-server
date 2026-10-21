"""Model-free contract tests; finite literal edits are not semantic proof."""
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bonsai_normalizer import DEFAULT_MODEL, DEFAULT_REVISION
from bonsai_literal_editor import (
    BonsaiLiteralEditor, SELECTION_PROMPT, candidate_spans, render_selection,
)


def response(content, **overrides):
    data = {'model': DEFAULT_MODEL, 'bonsai': {'revision': DEFAULT_REVISION},
            'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}
    data.update(overrides)
    result = io.BytesIO(json.dumps(data).encode())
    return result


class TestLiteralSelection(unittest.TestCase):
    def test_internal_adjective_and_separate_reactions_are_candidates(self):
        source = 'Ну блин, этот дурацкий скрипт готов. Это капец, проверь журнал.'
        spans = candidate_spans(source)
        self.assertEqual([s['text'] for s in spans], ['Ну блин, ', 'дурацкий ', 'Это капец, '])
        self.assertEqual([s['id'] for s in spans], [0, 1, 2])
        for span in spans:
            self.assertEqual(source[span['start']:span['end']], span['text'])
        self.assertEqual(render_selection(source, '{"delete":[0,1,2]}'),
                         'этот скрипт готов. проверь журнал.')

    def test_reconstruction_preserves_all_unselected_characters(self):
        source = ('  Этот дурацкий скрипт ждёт Анну 12 секунд.\n'
                  'Только если копия готова: срочно проверь rm -rf / tmp.  ')
        expected = source.replace('дурацкий ', '')
        self.assertEqual(render_selection(source, '{"delete":[0]}').encode(), expected.encode())
        self.assertEqual(render_selection(source, '{"delete":[]}').encode(), source.encode())

    def test_every_subset_copies_exact_unicode_occurrences(self):
        source = '🙂 Этот дурацкий отчёт е\u0301 готов. Этот дурацкий таймер — 2 с.  '
        spans = candidate_spans(source)
        self.assertEqual(len(spans), 2)
        for ids in ([], [0], [1], [0, 1]):
            expected_bytes = b''
            cursor = 0
            for index in ids:
                expected_bytes += source[cursor:spans[index]['start']].encode('utf-8')
                cursor = spans[index]['end']
            expected_bytes += source[cursor:].encode('utf-8')
            self.assertEqual(render_selection(source, json.dumps({'delete': ids})).encode(), expected_bytes)

    def test_protected_and_unsupported_contexts_have_no_candidates(self):
        sources = [
            'Это не дурацкий скрипт.',
            'Этот вовсе не дурацкий скрипт готов.',
            'Это не\nдурацкий скрипт.',
            'Этот дурацкий скрипт не готов.',
            '> Этот дурацкий скрипт.',
            'Путь /tmp/документ.дурацкий скрипт.',
            'Аргумент дурацкий скрипт сохрани.',
            'Заголовок дурацкий скрипт сохрани.',
            'Сохрани цитату «Этот дурацкий скрипт».',
            'Сохрани "дурацкий скрипт".',
            "Сохрани 'дурацкий скрипт'.",
            'Запиши “дурацкий скрипт”.',
            'Сохрани `дурацкий скрипт`.',
            'В названии дурацкий скрипт нет ошибки.',
            'В словах дурацкий скрипт исправь опечатку.',
            'Имя файла Дурацкий скрипт оставь как есть.',
            'Под именем Дурацкий скрипт зарегистрирован проект.',
            'Она сказала ‹Этот дурацкий скрипт›.',
            'Она сказала ‘Этот дурацкий скрипт’.',
            'Она сказала ‚Этот дурацкий скрипт‘.',
            'Слово дурацкий скрипт не сокращай.',
            'Это дурацкий скрипт.',
            'Очень дурацкий скрипт.',
            'Этот дурацкий /home/скрипт готов.',
            'Команда rm дурацкий скрипт.',
            'Казнить нельзя, помиловать.',
            'Перезапусти сервер только если копия готова.',
            'Этот необычный скрипт готов.',
            'Сохрани «незакрытую цитату. Этот дурацкий скрипт готов.',
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assertEqual(candidate_spans(source), [])
                self.assertEqual(render_selection(source, '{"delete":[]}'), source)
                with self.assertRaises(ValueError):
                    render_selection(source, '{"delete":[0]}')

    def test_finite_adjective_forms_are_not_an_open_word_deletion_channel(self):
        for adjective in ('чёртов', 'чертовой', 'проклятый', 'долбанный', 'дурацкие'):
            source = f'Этот {adjective} скрипт готов.'
            with self.subTest(adjective=adjective):
                self.assertEqual([s['text'] for s in candidate_spans(source)], [adjective + ' '])
        for text in ('дурацкий\nскрипт', 'дурацкий-скрипт', 'сверхдурацкий скрипт'):
            self.assertEqual(candidate_spans(text), [])

    def test_literal_use_still_needs_contextual_model_decision(self):
        # Literal "cursed" is a plot fact, not removable emotional filler.
        # Both selections are mechanically valid: reconstruction is not semantics.
        source = 'В сюжете этот проклятый замок населён духами.'
        self.assertEqual(len(candidate_spans(source)), 1)
        self.assertEqual(render_selection(source, '{"delete":[]}'), source)
        self.assertNotEqual(render_selection(source, '{"delete":[0]}'), source)

    def test_quoted_candidate_does_not_hide_separate_safe_candidate(self):
        source = 'Он сказал «дурацкий скрипт». Этот дурацкий отчёт готов.'
        self.assertEqual([s['text'] for s in candidate_spans(source)], ['дурацкий '])
        self.assertEqual(render_selection(source, '{"delete":[0]}'),
                         'Он сказал «дурацкий скрипт». Этот отчёт готов.')

    def test_strict_schema_rejects_prose_ids_and_duplicate_keys(self):
        source = 'Ну блин, этот дурацкий скрипт готов.'
        invalid = [
            '', 'source text', '```json\n{"delete":[0]}\n```', '[]', 'null',
            '{}', '{"delete":[],"text":"new"}', '{"delete":[],"delete":[0]}',
            '{"delete":true}', '{"delete":[true]}', '{"delete":[1.0]}',
            '{"delete":["0"]}', '{"delete":[-1]}', '{"delete":[2]}',
            '{"delete":[0,0]}', '{"delete":[1,0]}', '{"delete":[{}]}',
            '[' * 1500 + '0' + ']' * 1500,
        ]
        for content in invalid:
            with self.subTest(content=content), self.assertRaises(ValueError):
                render_selection(source, content)

    def test_inventory_is_bounded_and_request_local(self):
        editor = BonsaiLiteralEditor()
        first = 'Этот дурацкий скрипт готов.'
        second = 'Ну блин, этот долбанный таймер готов.'
        editor._messages_for_source(first)
        editor._messages_for_source(second)
        self.assertEqual(editor._render_candidate(first, '{"delete":[0]}'),
                         'Этот скрипт готов.')
        self.assertEqual(editor._render_candidate(second, '{"delete":[1]}'),
                         'Ну блин, этот таймер готов.')
        self.assertEqual(candidate_spans('Этот дурацкий скрипт. ' * 33), [])

    @patch('urllib.request.OpenerDirector.open')
    def test_real_transport_uses_ids_and_preserves_literal_source(self, opened):
        source = '  Этот дурацкий скрипт готов.  '
        opened.return_value = response('{"delete":[0]}')
        result, meta = BonsaiLiteralEditor().normalize(source)
        self.assertEqual(result, '  Этот скрипт готов.  ')
        self.assertEqual(meta['status'], 'applied')
        opened.assert_called_once()
        payload = json.loads(opened.call_args.args[0].data)
        self.assertEqual(payload['messages'][0]['content'], SELECTION_PROMPT)
        prompt = json.loads(payload['messages'][1]['content'])
        self.assertEqual(prompt['source'], source)
        self.assertEqual(prompt['candidates'], candidate_spans(source))
        self.assertEqual(payload['temperature'], 0.0)
        self.assertEqual(payload['seed'], 42)

    @patch('urllib.request.OpenerDirector.open')
    def test_empty_selection_is_unchanged_not_successful_edit(self, opened):
        source = 'Этот дурацкий скрипт готов.'
        opened.return_value = response('{"delete":[]}')
        result, meta = BonsaiLiteralEditor().normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta['status'], 'unchanged')
        self.assertEqual(meta['reason'], 'empty_edit_selection')

    @patch('urllib.request.OpenerDirector.open')
    def test_no_candidates_bypass_network_and_preserve_exact_text(self, opened):
        source = '  Это не дурацкий скрипт.\nКоманда rm -rf / tmp.  '
        result, meta = BonsaiLiteralEditor().normalize(source)
        self.assertEqual(result.encode(), source.encode())
        self.assertEqual(meta['status'], 'bypassed')
        self.assertEqual(meta['reason'], 'no_edit_candidates')
        opened.assert_not_called()

    @patch('urllib.request.OpenerDirector.open')
    def test_expanded_plan_bound_falls_back_before_network(self, opened):
        source = 'Этот дурацкий скрипт.' + '\x00' * 5900
        result, meta = BonsaiLiteralEditor().normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta['status'], 'fallback')
        self.assertEqual(meta['reason'], 'invalid_edit_plan')
        opened.assert_not_called()

    @patch('urllib.request.OpenerDirector.open')
    def test_bad_selection_and_protocol_return_exact_accepted_source(self, opened):
        source = '  Этот дурацкий скрипт готов.\n'
        for body, overrides, reason in [
            ('перезапусти сервер', {}, 'invalid_edit_selection'),
            ('{"delete":[8]}', {}, 'invalid_edit_selection'),
            ('{"delete":[0]}', {'model': 'wrong'}, 'model_mismatch'),
            ('{"delete":[0]}', {'bonsai': {'revision': 'wrong'}}, 'revision_mismatch'),
            ('\ud800', {}, 'invalid_content_encoding'),
        ]:
            with self.subTest(reason=reason):
                opened.return_value = response(body, **overrides)
                result, meta = BonsaiLiteralEditor().normalize(source)
                self.assertEqual(result, source)
                self.assertEqual(meta['status'], 'fallback')
                self.assertEqual(meta['reason'], reason)
        opened.side_effect = TimeoutError()
        result, meta = BonsaiLiteralEditor().normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta['reason'], 'timeout')


if __name__ == '__main__':
    unittest.main()
