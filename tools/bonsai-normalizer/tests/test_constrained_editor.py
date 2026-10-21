"""Model-free round 7 protocol tests; schema syntax is not semantic acceptance."""
import hashlib
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import mock_open, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bonsai_normalizer import (
    DEFAULT_MODEL, DEFAULT_REVISION, SYSTEM_PROMPT, BonsaiNormalizer,
    BonsaiNormalizerConfig, get_bonsai_normalizer,
)
from bonsai_literal_editor import (
    BonsaiLiteralEditor, SELECTION_PROMPT, candidate_spans, render_selection,
)
from bonsai_constrained_editor import BonsaiConstrainedLiteralEditor


def expected_format(count):
    return {'type': 'json_schema', 'json_schema': {
        'name': 'bonsai_literal_selection', 'strict': True,
        'schema': {'type': 'object', 'properties': {'delete': {
            'type': 'array', 'items': {'type': 'integer', 'enum': list(range(count))},
            'maxItems': count}}, 'required': ['delete'], 'additionalProperties': False}}}


def acknowledgement(response_format):
    profile = response_format['json_schema']
    canonical = json.dumps(profile['schema'], sort_keys=True, separators=(',', ':'),
                           ensure_ascii=False).encode('utf-8')
    return {'name': profile['name'], 'schema_sha256': hashlib.sha256(canonical).hexdigest()}


def response(content, ack, **overrides):
    data = {'model': DEFAULT_MODEL,
            'bonsai': {'revision': DEFAULT_REVISION, 'response_format': ack},
            'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}
    data.update(overrides)
    return io.BytesIO(json.dumps(data).encode('utf-8'))


class TestConstrainedEditor(unittest.TestCase):
    SOURCE = '  Ну блин, этот дурацкий скрипт готов.\n'

    def setUp(self):
        self.editor = BonsaiConstrainedLiteralEditor()
        self.ack = acknowledgement(expected_format(2))

    def assert_fallback(self, result, source, reason):
        text, meta = result
        self.assertEqual(text.encode('utf-8'), source.encode('utf-8'))
        self.assertEqual(meta['status'], 'fallback')
        self.assertEqual(meta['reason'], reason)

    @patch('urllib.request.OpenerDirector.open')
    def test_exact_transmitted_schema_digest_prompt_and_sampler(self, opened):
        opened.return_value = response('{"delete":[1]}', self.ack)
        text, meta = self.editor.normalize(self.SOURCE)
        self.assertEqual(text, '  Ну блин, этот скрипт готов.\n')
        self.assertEqual(meta['status'], 'applied')
        opened.assert_called_once()
        request = opened.call_args.args[0]
        payload = json.loads(request.data)
        literal_messages = BonsaiLiteralEditor()._messages_for_source(self.SOURCE)
        self.assertEqual(payload, {
            'model': DEFAULT_MODEL, 'messages': literal_messages, 'temperature': 0.0,
            'top_p': 0.8, 'top_k': 20, 'min_p': 0.0, 'presence_penalty': 0.0,
            'repetition_penalty': 1.0, 'seed': 42, 'max_tokens': 1024,
            'stream': False, 'response_format': expected_format(2),
        })
        self.assertEqual(payload['messages'][0]['content'], SELECTION_PROMPT)
        inventory = json.loads(payload['messages'][1]['content'])
        self.assertEqual(inventory, {'source': self.SOURCE, 'candidates': candidate_spans(self.SOURCE)})
        self.assertEqual(self.ack['schema_sha256'],
                         '8266e7021716abc596d506da67ab79af5a7bb848eb438bebabe9e69a5f812053')
        self.assertEqual(request.full_url, 'http://127.0.0.1:18091/v1/chat/completions')

    @patch('urllib.request.OpenerDirector.open')
    def test_valid_abstention_preserves_exact_source(self, opened):
        opened.return_value = response('{"delete":[]}', self.ack)
        text, meta = self.editor.normalize(self.SOURCE)
        self.assertEqual(text.encode(), self.SOURCE.encode())
        self.assertEqual(meta['status'], 'unchanged')
        self.assertEqual(meta['reason'], 'empty_edit_selection')

    @patch('urllib.request.OpenerDirector.open')
    def test_old_server_missing_and_malformed_ack_rejected_before_content(self, opened):
        invalid = [None, False, True, '', [], self.ack['schema_sha256'], {},
                   {'name': 'bonsai_literal_selection'},
                   {'schema_sha256': self.ack['schema_sha256']},
                   dict(self.ack, name='other'), dict(self.ack, schema_sha256='0' * 64),
                   dict(self.ack, schema_sha256=self.ack['schema_sha256'].upper()),
                   dict(self.ack, schema_sha256=[]), dict(self.ack, extra=True),
                   acknowledgement(expected_format(1))]
        for ack in invalid:
            with self.subTest(ack=ack):
                opened.return_value = response('not selection JSON', ack)
                with patch.object(self.editor, '_render_candidate') as render:
                    self.assert_fallback(self.editor.normalize(self.SOURCE), self.SOURCE,
                                         'response_format_unverified')
                    render.assert_not_called()
        # Old servers can give the correct revision without implementing this profile.
        for bonsai in ({'revision': DEFAULT_REVISION}, None, [], 'legacy'):
            with self.subTest(bonsai=bonsai):
                opened.return_value = response('{"delete":[0]}', None, bonsai=bonsai,
                                                 revision=DEFAULT_REVISION)
                self.assert_fallback(self.editor.normalize(self.SOURCE), self.SOURCE,
                                     'response_format_unverified')
        opened.return_value = response('{"delete":[0]}', None)
        data = json.loads(opened.return_value.getvalue())
        del data['bonsai']
        data['revision'] = DEFAULT_REVISION
        opened.return_value = io.BytesIO(json.dumps(data).encode())
        self.assert_fallback(self.editor.normalize(self.SOURCE), self.SOURCE,
                             'response_format_unverified')

    @patch('urllib.request.OpenerDirector.open')
    def test_verified_schema_does_not_relax_strict_selection_parser(self, opened):
        invalid = [
            '', 'source text', '```json\n{"delete":[0]}\n```', '[]', 'null', '{}',
            '{"delete":[],"text":"new"}', '{"delete":[],"delete":[0]}',
            '{"delete":true}', '{"delete":[true]}', '{"delete":[1.0]}',
            '{"delete":["0"]}', '{"delete":[-1]}', '{"delete":[2]}',
            '{"delete":[0,0]}', '{"delete":[1,0]}', '{"delete":[{}]}',
            '[' * 1500 + '0' + ']' * 1500,
        ]
        for content in invalid:
            with self.subTest(content=content):
                opened.return_value = response(content, self.ack)
                self.assert_fallback(self.editor.normalize(self.SOURCE), self.SOURCE,
                                     'invalid_edit_selection')

    @patch('urllib.request.OpenerDirector.open')
    def test_inherited_identity_finish_encoding_and_transport_fallback(self, opened):
        cases = [
            ('{"delete":[0]}', {'model': 'wrong'}, 'model_mismatch'),
            ('{"delete":[0]}', {'bonsai': {'revision': 'wrong', 'response_format': self.ack}},
             'revision_mismatch'),
            ('{"delete":[0]}', {'bonsai': {'response_format': self.ack}}, 'revision_missing'),
            ('{"delete":[0]}', {'choices': [{'finish_reason': 'length',
                                           'message': {'content': '{"delete":[0]}'}}]},
             'finish_reason_length'),
            ('\ud800', {}, 'invalid_content_encoding'),
            (123, {}, 'invalid_content_type'),
        ]
        for content, overrides, reason in cases:
            with self.subTest(reason=reason):
                opened.return_value = response(content, self.ack, **overrides)
                self.assert_fallback(self.editor.normalize(self.SOURCE), self.SOURCE, reason)
        opened.side_effect = TimeoutError('must not be copied')
        self.assert_fallback(self.editor.normalize(self.SOURCE), self.SOURCE, 'timeout')

    @patch('urllib.request.OpenerDirector.open')
    def test_final_lexical_guards_still_run_after_verified_rendering(self, opened):
        source = 'Этот дурацкий скрипт не готов 12 секунд в Slack, кажется.'
        # Simulate a future renderer defect; the inherited guards must remain active.
        for candidate, reason in [
            (source.replace('не ', ''), 'validation_negation_lost'),
            (source.replace('12 ', ''), 'validation_numeric_missing'),
            (source.replace('Slack', ''), 'validation_latin_missing'),
            (source.replace('кажется', ''), 'validation_qualifier_lost'),
            ('кажется, ' + source.replace(', кажется', ''), 'validation_word_order_changed'),
        ]:
            with self.subTest(reason=reason), patch.object(
                self.editor, '_render_candidate', return_value=candidate
            ):
                # The negated clause itself is shielded, so add a separate eligible clause.
                eligible = 'Этот дурацкий отчёт готов. ' + source
                opened.return_value = response('{"delete":[0]}', acknowledgement(expected_format(1)))
                self.assert_fallback(self.editor.normalize(eligible), eligible, reason)

    @patch('urllib.request.OpenerDirector.open')
    def test_no_candidates_bounds_and_protection_bypass_without_format(self, opened):
        cases = [('', 'empty_input'), (' \n ', 'empty_input'),
                 ('Этот необычный скрипт готов.', 'no_edit_candidates'),
                 ('Это не дурацкий скрипт.', 'no_edit_candidates'),
                 ('Сохрани «дурацкий скрипт».', 'no_edit_candidates'),
                 ('Команда rm дурацкий скрипт.', 'no_edit_candidates'),
                 ('Этот дурацкий скрипт. ' * 33, 'no_edit_candidates')]
        for source, reason in cases:
            with self.subTest(reason=reason):
                text, meta = self.editor.normalize(source)
                self.assertEqual(text, source)
                self.assertEqual(meta['status'], 'bypassed')
                self.assertEqual(meta['reason'], reason)
        self.assert_fallback(self.editor.normalize(self.SOURCE * 200), self.SOURCE * 200,
                             'input_length_exceeded')
        self.assert_fallback(self.editor.normalize('Этот дурацкий скрипт.' + '\x00' * 5900),
                             'Этот дурацкий скрипт.' + '\x00' * 5900, 'invalid_edit_plan')
        disabled = BonsaiConstrainedLiteralEditor(BonsaiNormalizerConfig(enabled=False))
        self.assertEqual(disabled.normalize(self.SOURCE)[1]['reason'], 'disabled_by_config')
        opened.assert_not_called()

    def test_schema_is_bounded_fresh_and_subclass_overrides_only_hook(self):
        for count in (1, 2, 32):
            source = 'Этот дурацкий скрипт. ' * count
            self.assertEqual(self.editor._response_format_for_source(source), expected_format(count))
        first = self.editor._response_format_for_source(self.SOURCE)
        first['json_schema']['schema']['properties']['delete']['items']['enum'].append(99)
        self.assertEqual(self.editor._response_format_for_source(self.SOURCE), expected_format(2))
        self.assertEqual({key for key in BonsaiConstrainedLiteralEditor.__dict__
                          if not key.startswith('__')}, {'_response_format_for_source'})
        schema = expected_format(2)['json_schema']['schema']
        self.assertNotIn('uniqueItems', schema['properties']['delete'])

    @patch('urllib.request.OpenerDirector.open')
    def test_response_format_planning_value_error_falls_back_before_network(self, opened):
        with patch.object(self.editor, '_response_format_for_source', side_effect=ValueError('private')):
            self.assert_fallback(self.editor.normalize(self.SOURCE), self.SOURCE, 'invalid_edit_plan')
        opened.assert_not_called()

    @patch('urllib.request.OpenerDirector.open')
    def test_default_and_old_literal_payload_and_output_remain_unchanged(self, opened):
        for editor, content, expected_status in (
            (BonsaiNormalizer(), self.SOURCE, 'applied'),
            (BonsaiLiteralEditor(), '{"delete":[]}', 'unchanged'),
        ):
            with self.subTest(editor=type(editor).__name__):
                self.assertIsNone(editor._response_format_for_source(self.SOURCE))
                opened.return_value = response(content, None)
                text, meta = editor.normalize(self.SOURCE)
                self.assertEqual(text, self.SOURCE.strip() if type(editor) is BonsaiNormalizer else self.SOURCE)
                self.assertEqual(meta['status'], expected_status)
                payload = json.loads(opened.call_args.args[0].data)
                self.assertNotIn('response_format', payload)
                self.assertEqual(payload['messages'], editor._messages_for_source(self.SOURCE))
                if type(editor) is BonsaiNormalizer:
                    self.assertEqual(payload['messages'][0]['content'], SYSTEM_PROMPT)

    def test_factory_still_selects_default_normalizer(self):
        with patch('os.path.isfile', return_value=True), patch('builtins.open', mock_open(read_data='{}')):
            self.assertIs(type(get_bonsai_normalizer('unused.json')), BonsaiNormalizer)

    def test_interleaved_calls_use_request_local_schema_and_ack(self):
        state_before = self.editor.__dict__.copy()
        barrier = threading.Barrier(2)
        sources = ['Этот дурацкий скрипт готов.', self.SOURCE]

        def opened(request, **_):
            payload = json.loads(request.data)
            source = json.loads(payload['messages'][1]['content'])['source']
            count = len(candidate_spans(source))
            self.assertEqual(payload['response_format'], expected_format(count))
            barrier.wait(timeout=3)
            return response(json.dumps({'delete': [count - 1]}),
                            acknowledgement(payload['response_format']))

        with patch.object(self.editor._opener, 'open', side_effect=opened), ThreadPoolExecutor(max_workers=2) as pool:
            for _ in range(5):
                futures = [pool.submit(self.editor.normalize, source) for source in sources]
                for source, future in zip(sources, futures):
                    text, meta = future.result(timeout=5)
                    expected = render_selection(source, json.dumps({'delete': [len(candidate_spans(source)) - 1]}))
                    self.assertEqual(text.encode(), expected.encode())
                    self.assertEqual(meta['status'], 'applied')
        self.assertEqual(self.editor.__dict__, state_before)

    @patch('urllib.request.OpenerDirector.open')
    def test_nested_call_cannot_replace_outer_expected_ack(self, opened):
        inner_source = 'Этот дурацкий скрипт готов.'

        def transport(request, **_):
            payload = json.loads(request.data)
            source = json.loads(payload['messages'][1]['content'])['source']
            if source == self.SOURCE:
                inner_text, inner_meta = self.editor.normalize(inner_source)
                self.assertEqual(inner_text, 'Этот скрипт готов.')
                self.assertEqual(inner_meta['status'], 'applied')
                # An outer response must not accept the inner request's valid digest.
                return response('{"delete":[0]}', acknowledgement(expected_format(1)))
            return response('{"delete":[0]}', acknowledgement(expected_format(1)))

        opened.side_effect = transport
        self.assert_fallback(self.editor.normalize(self.SOURCE), self.SOURCE,
                             'response_format_unverified')
        self.assertEqual(opened.call_count, 2)

    @patch('urllib.request.OpenerDirector.open')
    def test_actual_gateway_function_preserves_applied_abstained_and_rejected_results(self, opened):
        import test_gateway_seam_ast
        harness = test_gateway_seam_ast.TestExecutedGatewaySeam()
        source = 'Этот дурацкий скрипт готов.'
        for content, ack, expected, status in [
            ('{"delete":[0]}', acknowledgement(expected_format(1)), 'Этот скрипт готов.', 'applied'),
            ('{"delete":[]}', acknowledgement(expected_format(1)), source, 'unchanged'),
            ('{"delete":[0]}', None, source, 'fallback'),
        ]:
            with self.subTest(status=status):
                opened.return_value = response(content, ack)
                result, record, _, _, _ = harness._execute(real_normalizer=self.editor, asr_text=source)
                self.assertEqual(result.content['text'], expected)
                self.assertEqual(record['accepted_stt_text'], source)
                self.assertEqual(record['final_text'], expected)
                self.assertEqual(record['bonsai']['status'], status)


if __name__ == '__main__':
    unittest.main()
