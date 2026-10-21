"""Round31 wrapper tests reuse the real collector and client with socket traps."""
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bonsai_context_paragraph_screen as screen
from bonsai_paragraph_structurer import render_paragraphs
from test_paragraph_screen import Transport, SOURCE, NOW, DECK, admission


class ContextScreenChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inputs, self.output = self.root/'inputs.json', self.root/'result.json'
        cells = []
        for i, (name, representation) in enumerate(screen.ORDER):
            ids = [1] if i < 2 else []
            cells.append(dict(id=name, representation=representation, source=SOURCE,
                break_after=ids, expected=render_paragraphs(SOURCE, json.dumps({'break_after':ids})),
                status='applied' if ids else 'unchanged'))
        self.inputs.write_text(json.dumps({'cells': cells}))
        self.input_hash = screen.base.digest(self.inputs.read_bytes())
        for p in [patch.object(screen, 'INPUTS_SHA256', self.input_hash),
                  patch.object(socket.socket, 'connect', side_effect=AssertionError('socket forbidden'))]:
            p.start(); self.addCleanup(p.stop)
        self.observation = {**admission(), 'LFM_loaded_count': 0, 'matching_workers': [],
                            'five_preservation_hashes_match': True, 'caption_backend': 'minicpm_q8'}

    def run_screen(self, transport):
        return screen.collect(self.inputs, self.input_hash, self.output, 'test-token-'*4,
            self.observation, opener=transport, wall_clock=lambda:NOW, deck_observer=lambda:DECK)

    def test_four_counterbalanced_real_clients_and_only_inventory_difference(self):
        t = Transport()
        original = t.open
        def opened(request, timeout):
            if request.full_url.endswith('/v1/chat/completions'):
                t.content = '{"break_after":[1]}' if len(t.payloads)<2 else '{"break_after":[]}'
            return original(request, timeout)
        t.open = opened
        r = self.run_screen(t)
        self.assertTrue(r['completed'] and r['http_settled'] and r['deck_preserved'])
        self.assertEqual(r['model_calls'], 4)
        self.assertTrue(all(x['useful_grouping'] and x['insertion_plan_verified'] for x in r['rows']))
        for i, p in enumerate(t.payloads):
            candidates = json.loads(p['messages'][1]['content'])['candidates']
            self.assertEqual(set(candidates[0]), {'id', 'offset'} if i in (0,3) else {'id','before','after'})
        for pair in [t.payloads[:2], t.payloads[2:]]:
            a,b = pair
            self.assertEqual(a['messages'][0], b['messages'][0])
            self.assertEqual({k:v for k,v in a.items() if k!='messages'}, {k:v for k,v in b.items() if k!='messages'})
        paths=list(t.paths)
        with self.assertRaises(FileExistsError):self.run_screen(t)
        self.assertEqual(t.paths,paths)

    def test_unknown_outcome_stops_at_one_without_unload(self):
        t=Transport(fault=TimeoutError('unknown'))
        with self.assertRaisesRegex(RuntimeError,'Unresolved'):self.run_screen(t)
        r=json.loads(self.output.read_text())
        self.assertEqual(r['model_calls'],1)
        self.assertTrue(r['unknown_outcome'])
        self.assertNotIn('/unload',t.paths)

    def test_rejections_retained_no_repair_and_known_failure_settles(self):
        t=Transport(content='```json\n{"break_after":[1]}\n```')
        r=self.run_screen(t)
        self.assertEqual(r['model_calls'],4)
        self.assertTrue(r['completed'] and r['http_settled'])
        self.assertTrue(all(not x['useful_grouping'] and x['returned']==SOURCE for x in r['rows']))

    def test_manifest_runtime_and_preservation_reject_before_receipt_network(self):
        t=Transport()
        with patch.dict(screen.MODULE_HASHES,{'bonsai_context_paragraph.py':'wrong'}):
            with self.assertRaisesRegex(ValueError,'module drift'):self.run_screen(t)
        self.assertFalse(self.output.exists());self.assertEqual(t.paths,[])
        self.observation['LFM_loaded_count']=1
        with self.assertRaisesRegex(ValueError,'preservation admission'):self.run_screen(t)
        self.assertEqual(t.paths,[])
        self.assertFalse(self.output.exists())

    def test_paired_score_and_new_manifest_cannot_be_substituted(self):
        data=json.loads(self.inputs.read_text());data['cells'][0]['break_after']=[]
        self.inputs.write_text(json.dumps(data));new_hash=screen.base.digest(self.inputs.read_bytes())
        with self.assertRaisesRegex(ValueError,'manifest changed'):screen.validate_inputs(self.inputs,new_hash)
        with patch.object(screen,'INPUTS_SHA256',new_hash):
            with self.assertRaisesRegex(ValueError,'scorer changed'):screen.validate_inputs(self.inputs,new_hash)

    def test_dry_run_no_output_network_or_token(self):
        args=['screen','--inputs',str(self.inputs),'--output',str(self.output)]
        with patch.object(sys,'argv',args),patch('sys.stdout',new_callable=io.StringIO) as out:
            screen.main()
        self.assertEqual(json.loads(out.getvalue())['model_calls'],0)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
