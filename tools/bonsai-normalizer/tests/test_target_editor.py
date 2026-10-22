"""Socket/model-free singleton selection and unchanged inherited guard checks."""
import io
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bonsai_target_editor import BonsaiTargetEditor, TARGET_PROMPT
from bonsai_literal_editor import candidate_spans
from bonsai_normalizer import BonsaiNormalizer, get_bonsai_normalizer
from test_constrained_editor import acknowledgement, expected_format, response

SOURCE = 'Этот проклятый сканер готов. В сказке проклятый сундук хранит тайну.'


class TargetChecks(unittest.TestCase):
    def setUp(self):
        trap = patch.object(socket.socket, 'connect', side_effect=AssertionError('socket forbidden'))
        trap.start(); self.addCleanup(trap.stop)
        self.ack = acknowledgement(expected_format(1))

    def test_context_exact_slices_and_target_local_id(self):
        for target, span in enumerate(candidate_spans(SOURCE)):
            e = BonsaiTargetEditor(target=target)
            messages = e._messages_for_source(SOURCE)
            self.assertEqual(messages[0]['content'], TARGET_PROMPT)
            data = json.loads(messages[1]['content']); c = data['candidate']
            self.assertEqual(data['source'], SOURCE)
            self.assertEqual(c['id'], 0)
            self.assertEqual(c['before'] + c['text'] + c['after'], SOURCE)
            self.assertEqual(c['before'], SOURCE[:span['start']])
            self.assertEqual(c['text'], span['text'])
            self.assertEqual(e._response_format_for_source(SOURCE), expected_format(1))

    def test_only_target_can_be_deleted_and_strict_raw_parser_first(self):
        spans = candidate_spans(SOURCE)
        for target, span in enumerate(spans):
            e = BonsaiTargetEditor(target=target)
            self.assertEqual(e._render_candidate(SOURCE, '{"delete":[]}'), SOURCE)
            self.assertEqual(e._render_candidate(SOURCE, '{"delete":[0]}'), SOURCE[:span['start']]+SOURCE[span['end']:])
            for raw in ['{"delete":[1]}', '{"delete":[true]}', '{"delete":[0,0]}',
                        '{"delete":[],"delete":[0]}', '```json\n{"delete":[0]}\n```',
                        '{"delete":[0],"other":1}', '{"delete":[-1]}']:
                with self.subTest(target=target, raw=raw), self.assertRaises(ValueError):
                    e._render_candidate(SOURCE, raw)

    def test_invalid_target_and_plan_never_send(self):
        for t in [-1, True, 1.0, '0', 32]:
            with self.assertRaises(ValueError): BonsaiTargetEditor(target=t)
        e = BonsaiTargetEditor(target=2)
        with patch.object(e._opener, 'open') as opened:
            text, meta = e.normalize(SOURCE)
        self.assertEqual((text, meta['status'], meta['reason']), (SOURCE, 'fallback', 'invalid_edit_plan'))
        opened.assert_not_called()
        with self.assertRaises(AttributeError): e.target = 0

    def test_real_transport_payload_ack_fallback_and_interleaving(self):
        a, b = BonsaiTargetEditor(target=0), BonsaiTargetEditor(target=1)
        for e, selection, status in [(a, '[0]', 'applied'), (b, '[]', 'unchanged'),
                                      (b, '[0]', 'applied'), (a, '[]', 'unchanged')]:
            with patch.object(e._opener, 'open', return_value=response('{"delete":'+selection+'}', self.ack)) as opened:
                text, meta = e.normalize(SOURCE)
            self.assertEqual(meta['status'], status)
            payload = json.loads(opened.call_args.args[0].data)
            self.assertEqual(payload['response_format'], expected_format(1))
            self.assertEqual((payload['presence_penalty'], payload['temperature']), (0,0))
            self.assertEqual(text, e._render_candidate(SOURCE, '{"delete":'+selection+'}'))
        for ack in [None, acknowledgement(expected_format(2))]:
            with patch.object(a._opener, 'open', return_value=response('{"delete":[0]}', ack)):
                text, meta = a.normalize(SOURCE)
            self.assertEqual((text, meta['reason']), (SOURCE, 'response_format_unverified'))

    def test_shields_factory_and_default_normalizer_unselected(self):
        e = BonsaiTargetEditor(target=0)
        with patch.object(e._opener, 'open') as opened:
            self.assertEqual(e.normalize('Это не проклятый сундук.')[1]['status'], 'bypassed')
        opened.assert_not_called()
        with patch('os.path.isfile', return_value=True), patch('builtins.open', return_value=io.StringIO('{}')):
            self.assertIs(type(get_bonsai_normalizer('synthetic')), BonsaiNormalizer)


if __name__ == '__main__': unittest.main()
