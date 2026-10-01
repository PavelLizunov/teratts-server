import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import name_evidence as evidence
import vocabulary_bank as bank
import vocabulary_review as review
from voice_corpus import Corpus

class Tests(unittest.TestCase):
    def test_variants_unicode_repeats_and_ambiguous(self):
        text="🙂 гитха, гетхаб, git hub, на git, gitab, hub git, GitLab, GitHub."
        rows=evidence.candidates(text)
        self.assertEqual([r['surface'] for r in rows],["гитха","гетхаб","git hub","git","gitab","hub git","GitLab","GitHub"])
        for r in rows:self.assertEqual(text[r['start']:r['end']],r['surface'])
        self.assertEqual(next(r for r in rows if r['surface']=='git')['label'],'ambiguous')
        self.assertEqual(len(evidence.candidates("git git git")),3)
    def test_protected_and_unrelated(self):
        self.assertFalse(evidence.candidates("https://github.com/user `git hub` ```git```"))
        self.assertFalse(evidence.candidates("погода была хорошая"))
        self.assertFalse(evidence.candidates("GitHub",canonical="other"))
    def test_backfill_idempotence_raw_not_corrected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'c';corpus=Corpus(root,min_free_bytes=0)
            corpus.save(b'audio',{'kind':'stt','raw_text':'на gitab','final_text':'на GitHub'})
            bank.collect(root,idle_seconds=0);bank.collect(root,idle_seconds=0)
            c=sqlite3.connect(root/bank.DB_NAME)
            try:
                self.assertEqual(c.execute('select count(*) from name_mentions').fetchone()[0],1)
                self.assertEqual(c.execute('select surface from name_mentions').fetchone()[0],'gitab')
                self.assertEqual(c.execute('select text from name_documents').fetchone()[0],'на gitab')
            finally:c.close()
    def test_review_decision_only_occurrence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'c';corpus=Corpus(root,min_free_bytes=0)
            corpus.save(b'audio',{'kind':'stt','raw_text':'на git, потом GitLab','final_text':'на git, потом GitLab'})
            bank.collect(root,idle_seconds=0)
            data=review.name_list(root);self.assertEqual(data['total'],2)
            item=next(i for i in data['items'] if i['surface']=='git')
            before=review.summary(root)['confirmed_terms']
            payload={'kind':'name_occurrence','key':item['key'],'revision':item['revision'],'decision':'yes','value':'','request_id':'synthetic_name_review_001'}
            self.assertTrue(review.save_feedback(root,payload)['saved'])
            self.assertEqual(review.name_list(root)['total'],1)
            self.assertEqual(review.summary(root)['confirmed_terms'],before)
            c=sqlite3.connect(root/bank.DB_NAME)
            try:self.assertFalse(json.loads(c.execute('select context_json from feedback_context').fetchone()[0])['alias_approved'])
            finally:c.close()
            self.assertTrue(review.save_feedback(root,payload)['duplicate'])
    def test_existing_source_still_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'c';corpus=Corpus(root,min_free_bytes=0)
            sid=corpus.save(b'audio',{'kind':'stt','raw_text':'Гетхаб','final_text':'Гетхаб'})
            c=bank.open_database(root)
            with c:c.execute('insert into sources values(?,?,?)',(sid+'.tar','stt',0))
            c.close();bank.collect(root,idle_seconds=0)
            self.assertEqual(review.name_list(root)['total'],1)
if __name__=='__main__':unittest.main(verbosity=2)
