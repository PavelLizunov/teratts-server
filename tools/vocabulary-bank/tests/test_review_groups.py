import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import review_groups as groups
import vocabulary_bank as bank
import vocabulary_review as review
from voice_corpus import Corpus

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'c';self.corpus=Corpus(self.root,min_free_bytes=0);self.corpus.status()
    def tearDown(self):self.tmp.cleanup()
    def insert(self,text='Этот repository открыт.',sample='same-audio',stage='stt_raw',source='one',canonical='Разработка'):
        c=bank.open_database(self.root);word='repository';start=text.index(word)
        with c:
            c.execute('INSERT INTO name_documents VALUES(?,?,?,?,?)',(source,stage,text,sample,hashlib.sha256(text.encode()).hexdigest()))
            c.execute('INSERT INTO name_mentions(source,stage,canonical,start,end,surface,reason,label) VALUES(?,?,?,?,?,?,?,?)',(source,stage,canonical,start,start+len(word),word,'test','ambiguous'))
        identity=c.execute('select last_insert_rowid()').fetchone()[0];c.close();return identity
    def test_same_sample_stage_duplicates_grouped_not_different(self):
        self.insert();self.insert(stage='teacher_blind',source='two');self.insert(text='Этот repository открыт!',stage='teacher_hinted',source='three')
        self.insert(sample='different-audio',source='four')
        self.insert(text='Другой repository закрыт.',source='five')
        data=review.name_list(self.root,canonical='Разработка')
        self.assertEqual(data['total'],3)
        group=next(i for i in data['items'] if i['evidence_count']==3)
        self.assertEqual(group['stage'],'stt_raw')
        self.assertEqual(data['grouping']['duplicate_stage_rows_hidden'],2)
    def test_repetition_position_kept(self):
        identity=self.insert(text='repository repository')
        c=bank.open_database(self.root)
        with c:c.execute('INSERT INTO name_mentions(source,stage,canonical,start,end,surface,reason,label) VALUES(?,?,?,?,?,?,?,?)',('one','stt_raw','Разработка',11,21,'repository','test','ambiguous'))
        c.close();self.assertEqual(review.name_list(self.root,canonical='Разработка')['total'],2)
    def test_group_feedback_hides_all_idempotent(self):
        self.insert();self.insert(stage='teacher_blind',source='two')
        item=review.name_list(self.root,canonical='Разработка')['items'][0]
        p={'kind':'name_occurrence','key':item['key'],'revision':item['revision'],'decision':'custom','value':'repository','request_id':'synthetic_group_save_001'}
        review.save_feedback(self.root,p);self.assertEqual(review.name_list(self.root,canonical='Разработка')['total'],0)
        self.assertTrue(review.save_feedback(self.root,p)['duplicate'])
        c=review.connect(self.root)
        try:self.assertEqual(c.execute('select count(*) from feedback').fetchone()[0],2)
        finally:c.close()
    def test_conflict_visible_and_stale_rejected(self):
        a=self.insert();b=self.insert(stage='teacher_blind',source='two')
        c=bank.open_database(self.root)
        with c:
            c.execute('CREATE TABLE feedback(request_id TEXT PRIMARY KEY,target_kind TEXT,target_key TEXT,decision TEXT,value TEXT,created_ns INTEGER)')
            for i,decision in [(a,'unsure'),(b,'no')]:c.execute('INSERT INTO feedback VALUES(?,?,?,?,?,?)',(f'old{i}','name_occurrence',str(i),decision,'',i))
        c.close();data=review.name_list(self.root,canonical='Разработка');self.assertEqual(data['total'],1)
        item=data['items'][0];self.assertTrue(item['feedback_conflict'])
        self.insert(stage='teacher_hinted',source='new')
        p={'kind':'name_occurrence','key':item['key'],'revision':item['revision'],'decision':'unsure','value':'','request_id':'synthetic_stale_group_001'}
        with self.assertRaises(review.ReviewError) as e:review.save_feedback(self.root,p)
        self.assertEqual(e.exception.status,409)
    def test_specialized_duplicate_routes_not_all_name_meanings(self):
        self.insert(canonical='плагины');c=bank.open_database(self.root)
        with c:c.execute('INSERT INTO name_mentions(source,stage,canonical,start,end,surface,reason,label) VALUES(?,?,?,?,?,?,?,?)',('one','stt_raw','Разработка',5,15,'repository','test','ambiguous'))
        c.close();data=review.name_list(self.root,canonical='Разработка')
        self.assertEqual(data['total'],0);self.assertEqual(data['grouping']['routed_to_specific_queue'],1)
        self.assertEqual(review.name_list(self.root,canonical='плагины')['total'],1)
if __name__=='__main__':unittest.main(verbosity=2)
