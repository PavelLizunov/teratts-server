"""Real client/collector seams with fake transport; no native/model execution."""
import base64
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bonsai_target_screen as screen
from test_paragraph_screen import Transport, NOW, DECK, admission
from test_constrained_editor import acknowledgement, expected_format
from test_target_editor import SOURCE


class TargetScreenChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.inputs=self.root/'inputs.json';self.output=self.root/'result.json'
        cells=[]
        for i,(name,target,ids) in enumerate(screen.ORDER):
            source = SOURCE if i<2 else SOURCE.replace('сканер','принтер')
            e=screen.BonsaiTargetEditor(target=target)
            cells.append(dict(id=name,target=target,delete=ids,source=source,
                expected=e._render_candidate(source,json.dumps({'delete':ids})),status='applied' if ids else 'unchanged'))
        self.inputs.write_text(json.dumps({'cells':cells}));self.input_hash=screen.base.digest(self.inputs.read_bytes())
        for p in [patch.object(screen,'INPUTS_SHA256',self.input_hash),
                  patch.object(socket.socket,'connect',side_effect=AssertionError('socket forbidden'))]:
            p.start();self.addCleanup(p.stop)
        self.admission={**admission(),'LFM_loaded_count':0,'matching_workers':[],
                        'five_preservation_hashes_match':True,'caption_backend':'minicpm_q8'}

    def transport(self, *, wrong=False, ack=True, **kwargs):
        t=Transport(**kwargs);original=t.open
        def opened(request, timeout):
            if request.full_url.endswith('/v1/chat/completions') and not kwargs.get('fault'):
                if not kwargs.get('content'):
                    ids=([0] if wrong else screen.ORDER[len(t.payloads)][2])
                    t.content=json.dumps({'delete':ids})
                raw=original(request,timeout).read();data=json.loads(raw)
                if ack:data['bonsai']['response_format']=acknowledgement(expected_format(1))
                return io.BytesIO(json.dumps(data).encode())
            return original(request,timeout)
        t.open=opened;return t

    def collect(self,t,**kwargs):
        return screen.collect(self.inputs,self.input_hash,self.output,'synthetic-token-'*4,self.admission,
            opener=t,wall_clock=lambda:NOW,deck_observer=lambda:DECK,**kwargs)

    def test_real_four_clients_schema_target_copy_and_once_only(self):
        t=self.transport();r=self.collect(t)
        self.assertTrue(r['completed'] and r['http_settled'] and r['deck_preserved'])
        self.assertEqual(r['model_calls'],4)
        self.assertTrue(all(x['useful_target_result'] and x['exact_copy_verified'] for x in r['rows']))
        self.assertEqual(r['prompt_sha256'],screen.base.digest(screen.TARGET_PROMPT.encode()))
        for p in t.payloads:
            self.assertEqual(p['response_format'],expected_format(1))
            self.assertNotIn('candidates',json.loads(p['messages'][1]['content']))
        before=list(t.paths)
        with self.assertRaises(FileExistsError):self.collect(t)
        self.assertEqual(t.paths,before)
        self.assertNotIn('synthetic-token-',self.output.read_text())

    def test_select_all_semantic_failures_retained_not_fallback_success(self):
        r=self.collect(self.transport(wrong=True))
        self.assertTrue(r['completed'])
        self.assertEqual(sum(x['useful_target_result'] for x in r['rows']),2)
        self.assertTrue(all(x['metadata']['status']=='applied' for x in r['rows']))

    def test_ack_mismatch_is_known_stop_settlement_not_next_cell(self):
        t=self.transport(ack=False)
        with self.assertRaisesRegex(ValueError,'acknowledgement'):self.collect(t)
        r=json.loads(self.output.read_text());self.assertEqual(r['model_calls'],1)
        self.assertFalse(r['unknown_outcome']);self.assertTrue(r['http_settled'])
        self.assertEqual(r['rows'][0]['returned'],r['rows'][0]['source'])

    def test_unknown_outcome_no_unload_replay_or_next_request(self):
        t=self.transport(fault=TimeoutError('unknown'))
        with self.assertRaisesRegex(RuntimeError,'Unresolved'):self.collect(t)
        r=json.loads(self.output.read_text());self.assertTrue(r['unknown_outcome'])
        self.assertEqual(r['model_calls'],1);self.assertNotIn('/unload',t.paths)

    def test_fenced_response_rejected_without_repair_keeps_all_denominators(self):
        r=self.collect(self.transport(content='```json\n{"delete":[0]}\n```'))
        self.assertEqual(r['model_calls'],4)
        self.assertTrue(all(not x['useful_target_result'] and not x['strict_selection_valid'] for x in r['rows']))
        self.assertTrue(all(x['returned']==x['source'] and x['metadata']['status']=='fallback' for x in r['rows']))

    def test_manifest_and_runtime_drift_fail_before_output_network(self):
        t=self.transport()
        with patch.dict(screen.MODULE_HASHES,{'bonsai_target_editor.py':'wrong'}):
            with self.assertRaisesRegex(ValueError,'module drift'):self.collect(t)
        self.assertFalse(self.output.exists());self.assertEqual(t.paths,[])
        self.inputs.write_text(self.inputs.read_text()+' ')
        with self.assertRaisesRegex(ValueError,'manifest changed'):self.collect(t)
        self.assertFalse(self.output.exists())

    def test_dry_run_no_result_token_or_network(self):
        args=['screen','--inputs',str(self.inputs),'--output',str(self.output)]
        with patch.object(sys,'argv',args),patch('sys.stdout',new_callable=io.StringIO) as output:screen.main()
        self.assertEqual(json.loads(output.getvalue())['model_calls'],0);self.assertFalse(self.output.exists())


if __name__ == '__main__':unittest.main()
