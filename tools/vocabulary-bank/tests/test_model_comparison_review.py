import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import model_comparison_review as model
import vocabulary_review as review
import vocabulary_bank as bank
from voice_corpus import Corpus


def completed_summary(n=24):
    rows=[]
    for i in range(n):
        primary=f'Исходная фраза {i} GitHub';candidate='' if i<10 else f'Другой текст {i} GitHub' if i<21 else primary
        rows.append({'audio_sha256':f'{i:064x}','status':'completed','candidate_text':candidate,'duration_s':1+i/10,
          'comparisons':[{'sample_id':f'sample-{i}','baseline_raw':primary,'same_normalized_text':i>=21,'category':'agreement' if i>=21 else 'substantial_difference','token_agreement_ratio':1 if i>=21 else 0.4}]})
    return {'all_manifest_results_successful':True,'model_sha256':model.MODEL_SHA,'frozen_manifest_sha256':model.MANIFEST_SHA,'total_unique_audio':n,'results':rows}

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'voice-corpus';self.corpus=Corpus(self.root,min_free_bytes=0);self.corpus.status()
        c=bank.open_database(self.root);model.import_records(c,model.build_records(completed_summary()));c.close()
    def tearDown(self):self.temp.cleanup()
    def test_priority_unique_import_idempotent_and_pair_guard(self):
        c=review.connect(self.root,write=True)
        try:
            self.assertEqual(model.import_records(c,model.build_records(completed_summary())),0)
            self.assertEqual(c.execute('select count(*) from model_comparisons').fetchone()[0],24)
            self.assertEqual(c.execute('select sum(priority) from model_comparisons').fetchone()[0],20)
        finally:c.close()
        s=completed_summary();s['results'].append(s['results'][0]);s['total_unique_audio']=25
        with self.assertRaises(ValueError):model.build_records(s)
    def test_filters_and_preference_not_gold(self):
        data=review.comparison_list(self.root);self.assertEqual(data['total'],20)
        self.assertEqual(review.comparison_list(self.root,filter='all')['total'],24)
        self.assertEqual(review.comparison_list(self.root,filter='empty')['total'],10)
        item=data['items'][0]
        payload={'kind':'model_comparison','key':item['key'],'revision':item['revision'],'decision':'both_bad','value':'','request_id':'synthetic_model_preference001'}
        result=review.save_feedback(self.root,payload);self.assertFalse(result['training_approved'])
        self.assertEqual(review.comparison_list(self.root)['total'],19)
        self.assertTrue(review.save_feedback(self.root,payload)['duplicate'])
        c=review.connect(self.root)
        try:
            context=json.loads(c.execute('select context_json from feedback_context').fetchone()[0])
            self.assertFalse(context['human_gold']);self.assertFalse(context['training_approved'])
        finally:c.close()
    def test_frozen_audio_exact_boundary(self):
        item=review.comparison_list(self.root)['items'][0]
        with self.assertRaises(review.ReviewError):review.comparison_audio(self.root,item['key'])
        with self.assertRaises(ValueError):model.frozen_audio_path(self.root,'../../etc/passwd')
        path=model.frozen_audio_path(self.root,item['key']);path.parent.mkdir(parents=True)
        path.write_bytes(b'changed')
        with self.assertRaises(review.ReviewError):review.comparison_audio(self.root,item['key'])
    def test_custom_whole_transcript_and_stale(self):
        item=review.comparison_list(self.root)['items'][0]
        p={'kind':'model_comparison','key':item['key'],'revision':'old','decision':'custom','value':'Правильная фраза','request_id':'synthetic_model_custom_001'}
        with self.assertRaises(review.ReviewError):review.save_feedback(self.root,p)
        p['revision']=item['revision'];self.assertTrue(review.save_feedback(self.root,p)['saved'])
        self.assertEqual(review.summary(self.root)['confirmed_terms'],3)
if __name__=='__main__':unittest.main(verbosity=2)
