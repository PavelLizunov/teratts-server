from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import vocabulary_bank as bank
import vocabulary_review as review
import repair_opening_intent as repair
from voice_corpus import Corpus

class Tests(unittest.TestCase):
    def test_append_only_idempotent_no_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'c';corpus=Corpus(root,min_free_bytes=0)
            corpus.save(b'w',{'kind':'stt','raw_text':'Ну, есть задача','final_text':'x'})
            corpus.save(b'w2',{'kind':'stt','raw_text':'Ну, другая задача','final_text':'x'})
            bank.collect(root,idle_seconds=0)
            rows=review.name_list(root,canonical='Смотри')['items']
            c=sqlite3.connect(root/bank.DB_NAME)
            with c:
                c.execute('CREATE TABLE IF NOT EXISTS feedback(request_id TEXT PRIMARY KEY,target_kind TEXT,target_key TEXT,decision TEXT,value TEXT,created_ns INTEGER)')
                for i,row in enumerate(rows):c.execute('INSERT INTO feedback VALUES(?,?,?,?,?,?)',(f'original{i}','name_occurrence',row['key'],'yes' if i==0 else 'no','',10+i))
            c.close()
            result=repair.repair(root);self.assertEqual(result['repaired'],1)
            self.assertEqual(repair.repair(root)['repaired'],0)
            c=sqlite3.connect(root/bank.DB_NAME)
            try:
                self.assertEqual(c.execute('select count(*) from feedback').fetchone()[0],3)
                self.assertEqual(c.execute("select decision,value from feedback where request_id like 'repair_opening_%'").fetchone(),('custom','Ну'))
                self.assertEqual(c.execute("select decision from feedback where request_id='original1'").fetchone()[0],'no')
            finally:c.close()
    def test_generic_yes_blocked_explicit_nu_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'c';corpus=Corpus(root,min_free_bytes=0);corpus.save(b'w',{'kind':'stt','raw_text':'Ну, есть задача','final_text':'x'})
            bank.collect(root,idle_seconds=0);row=review.name_list(root,canonical='Смотри')['items'][0]
            data={'kind':'name_occurrence','key':row['key'],'revision':row['revision'],'request_id':'synthetic_opening_test_001','decision':'yes','value':''}
            with self.assertRaises(review.ReviewError):review.save_feedback(root,data)
            data.update(decision='custom',value='Ну');self.assertTrue(review.save_feedback(root,data)['saved'])
if __name__=='__main__':unittest.main(verbosity=2)
