"""Model-free context evidence, inheritance and exact source-copy tests."""
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bonsai_context_paragraph import BonsaiContextParagraphStructurer, context_candidates
from bonsai_normalizer import BonsaiNormalizer, DEFAULT_MODEL, DEFAULT_REVISION, get_bonsai_normalizer
from bonsai_paragraph_structurer import BonsaiParagraphStructurer, PARAGRAPH_PROMPT, paragraph_boundaries, render_paragraphs


class ContextChecks(unittest.TestCase):
    SOURCE = 'Первое сообщение готово. Второе сообщение принято. Третье сообщение отправлено.'

    def test_context_is_exact_adjacent_slices_and_same_ids_not_offsets(self):
        source = self.SOURCE + '\n\nХвост сохранён.'
        plan = paragraph_boundaries(source)
        rows = context_candidates(source)
        offsets = [0, *[p['offset'] for p in plan], len(source)]
        self.assertEqual(len(rows), len(plan))
        for i, row in enumerate(rows):
            self.assertEqual(set(row), {'id', 'before', 'after'})
            self.assertEqual(row['id'], plan[i]['id'])
            self.assertEqual(row['before'], source[offsets[i]:offsets[i+1]])
            self.assertEqual(row['after'], source[offsets[i+1]:offsets[i+2]])
            self.assertTrue(row['before'].endswith(' '))
        rows[0]['before'] = 'changed'
        self.assertNotEqual(rows, context_candidates(source))

    def test_only_representation_changes_prompt_source_sampler_and_renderer_stay(self):
        old = BonsaiParagraphStructurer()._messages_for_source(self.SOURCE)
        new = BonsaiContextParagraphStructurer()._messages_for_source(self.SOURCE)
        self.assertEqual(old[0], new[0])
        self.assertEqual(new[0]['content'], PARAGRAPH_PROMPT)
        a, b = [json.loads(x[1]['content']) for x in [old, new]]
        self.assertEqual(a['source'], b['source'])
        self.assertEqual([c['id'] for c in a['candidates']], [c['id'] for c in b['candidates']])
        self.assertIs(BonsaiContextParagraphStructurer.normalize, BonsaiParagraphStructurer.normalize)
        self.assertIs(BonsaiContextParagraphStructurer._render_candidate, BonsaiParagraphStructurer._render_candidate)
        self.assertEqual(BonsaiContextParagraphStructurer().config, BonsaiParagraphStructurer().config)

    def test_shields_and_existing_newlines_unchanged_no_candidates(self):
        for source in ['Одна мысль.', 'echo\n' + self.SOURCE, '«Незавершённая цитата. Дальше текст.',
                       'Первая готова.\nВторая готова.']:
            self.assertEqual(context_candidates(source), [])

    def test_expanded_request_bound_rejects_without_clipping(self):
        source = 'а' * 10000 + '. ' + 'Б' * 10000 + '.'
        with self.assertRaisesRegex(ValueError, 'plan_too_large'):
            BonsaiContextParagraphStructurer()._messages_for_source(source)

    def test_real_normalize_transmits_context_and_exact_insertion_or_fallback(self):
        editor = BonsaiContextParagraphStructurer()
        for content, status in [('{"break_after":[1]}', 'applied'), ('{"break_after":[]}', 'unchanged'),
                                ('```json\n{"break_after":[1]}\n```', 'fallback')]:
            data = {'model': DEFAULT_MODEL, 'revision': DEFAULT_REVISION,
                    'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}
            with patch.object(editor._opener, 'open', return_value=io.BytesIO(json.dumps(data).encode())) as opened:
                text, meta = editor.normalize(self.SOURCE)
            self.assertEqual(meta['status'], status)
            self.assertEqual(text, render_paragraphs(self.SOURCE, content) if status != 'fallback' else self.SOURCE)
            payload = json.loads(opened.call_args.args[0].data)
            self.assertEqual(json.loads(payload['messages'][1]['content'])['candidates'], context_candidates(self.SOURCE))
            self.assertEqual((payload['temperature'], payload['presence_penalty'], payload['seed']), (0, 0, 42))
            self.assertNotIn('response_format', payload)
            opened.assert_called_once()

    def test_factory_not_changed_and_inherited_exact_copy_plan(self):
        with patch('os.path.isfile', return_value=True), patch('builtins.open', return_value=io.StringIO('{}')):
            self.assertIs(type(get_bonsai_normalizer('synthetic')), BonsaiNormalizer)
        for ids in [[], [0], [1], [0, 1]]:
            response = json.dumps({'break_after': ids})
            self.assertEqual(BonsaiContextParagraphStructurer()._render_candidate(self.SOURCE, response),
                             render_paragraphs(self.SOURCE, response))


if __name__ == '__main__':
    unittest.main()
