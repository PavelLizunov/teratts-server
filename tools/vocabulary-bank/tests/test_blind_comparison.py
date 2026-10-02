import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import blind_comparison as blind
import model_comparison_review as model
import vocabulary_review as review
import vocabulary_bank as bank
from voice_corpus import Corpus
from test_model_comparison_review import completed_summary

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'corpus';Corpus(self.root,min_free_bytes=0).status()
        c=bank.open_database(self.root);model.import_records(c,model.build_records(completed_summary(24)));c.close()
    def tearDown(self):self.tmp.cleanup()
    def test_balanced_stable_private_only(self):
        c=review.connect(self.root,write=True)
        try:
            rows=c.execute('select * from blind_assignments order by token').fetchall()
            self.assertEqual(len(rows),24);self.assertEqual(sum(r[2] for r in rows),12)
            blind.initialize(c);self.assertEqual(rows,c.execute('select * from blind_assignments order by token').fetchall())
            data=blind.public_rows(c,filter='all')
            for item in data['items']:
                self.assertEqual(len(item['key']),32)
                for forbidden in ['primary','candidate','model_sha','sample_ids','audio_sha','option1_primary']:
                    self.assertNotIn(forbidden,item)
                row=blind.private_row(c,item['key'])
                self.assertEqual(item['option1_text'],row[5] if row[2] else row[6])
            serialized=json.dumps(data)
            self.assertNotIn('candidate_empty',serialized);self.assertNotIn('primary_empty',serialized)
            self.assertNotIn('primary_text',serialized)
        finally:c.close()
    def test_vote_resolves_correctly_and_old_nonblind_not_reused(self):
        old=review.comparison_list(self.root)['items'][0]
        review.save_feedback(self.root,{'kind':'model_comparison','key':old['key'],'revision':old['revision'],'decision':'primary','value':'','request_id':'old_nonblind_test_0001'})
        before=review.blind_list(self.root)['total'];self.assertEqual(before,20)
        item=review.blind_list(self.root)['items'][0]
        c=review.connect(self.root);private=blind.private_row(c,item['key']);c.close()
        p={'kind':'blind_comparison','key':item['key'],'revision':item['revision'],'decision':'option1','value':'','request_id':'blind_test_vote_0001'}
        result=review.save_feedback(self.root,p);self.assertFalse(result['training_approved'])
        self.assertTrue(review.save_feedback(self.root,p)['duplicate']);self.assertEqual(review.blind_list(self.root)['total'],before-1)
        c=review.connect(self.root)
        try:
            audit=json.loads(c.execute('select context_json from feedback_context where request_id=?',(p['request_id'],)).fetchone()[0])
            self.assertEqual(audit['resolved_choice'],'primary' if private[2] else 'candidate')
            self.assertEqual(blind.resolve_choice(private,'option2'),'candidate' if private[2] else 'primary')
            self.assertEqual(c.execute("select count(*) from feedback where target_kind='model_comparison'").fetchone()[0],1)
        finally:c.close()
        public=review.blind_list(self.root,pending=False)
        self.assertNotIn('resolved_choice',json.dumps(public));self.assertNotIn('option1_is_primary',json.dumps(public))
    def test_old_revision_and_named_model_choice_refused(self):
        item=review.blind_list(self.root)['items'][0]
        p={'kind':'blind_comparison','key':item['key'],'revision':'old','decision':'option2','value':'','request_id':'blind_stale_test_0001'}
        with self.assertRaises(review.ReviewError):review.save_feedback(self.root,p)
        p.update(revision=item['revision'],decision='primary')
        with self.assertRaises(review.ReviewError):review.save_feedback(self.root,p)
    def test_opaque_audio_path_and_no_mapping_stats(self):
        data=review.blind_list(self.root);self.assertNotIn('categories',data['comparison_stats'])
        with self.assertRaises(review.ReviewError):review.blind_audio(self.root,'../etc/passwd')
        item=data['items'][0]
        with self.assertRaises(review.ReviewError):review.blind_audio(self.root,item['key'])
if __name__=='__main__':unittest.main(verbosity=2)
