from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import technical_terms as terms
import vocabulary_bank as bank
import vocabulary_review as review
from voice_corpus import Corpus

class Tests(unittest.TestCase):
    def test_git_ambiguities_and_forms(self):
        text='Контрибьютор запушил коммит, потом пул реквест, репозиторий и GitLab.'
        result=terms.candidates(text,'Разработка');surfaces=[r['surface'] for r in result]
        for surface in ['Контрибьютор','запушил','коммит','пул реквест','репозиторий','GitLab']:self.assertIn(surface,surfaces)
        self.assertNotIn('пул',surfaces)
        self.assertEqual(terms.suggestions('пул','Разработка'),['pull','pool','пул'])
        self.assertNotEqual(terms.suggestions('пуш','Разработка'),terms.suggestions('пул','Разработка'))
        self.assertEqual(terms.suggestions('GitLab','Разработка'),['GitLab'])
    def test_linux_and_no_short_fuzzy_commands(self):
        text='Linux судо пакман systemctl, баш и Docker, а sudo rm в коде `sudo rm`.'
        result=terms.candidates(text,'Linux')
        self.assertTrue(any(r['surface']=='судо' for r in result))
        self.assertTrue(any(r['surface']=='systemctl' for r in result))
        self.assertFalse(terms.suggestions('суд','Linux'))
        self.assertFalse(terms.suggestions('su','Linux'))
        self.assertFalse(terms.candidates('обычная хорошая погода контроль популярно пуля пульт пульс пультами','Разработка'))
    def test_context_offsets_and_protected(self):
        text='🙂 контрибьютор и pull request, https://github.com/push `пуш`'
        rows=terms.candidates(text,'Разработка')
        for r in rows:self.assertEqual(text[r['start']:r['end']],r['surface'])
        self.assertFalse(any(r['surface']=='пуш' for r in rows))
        self.assertTrue(any(r['surface']=='pull request' for r in rows))
    def test_persistent_topic_feedback_exact_not_yes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'c';corpus=Corpus(root,min_free_bytes=0)
            corpus.save(b'wave',{'kind':'stt','raw_text':'Нужен пул, судо и контрибьютор','final_text':'unchanged'})
            bank.collect(root,idle_seconds=0);bank.collect(root,idle_seconds=0)
            item=next(r for r in review.name_list(root,canonical='Разработка')['items'] if r['surface']=='пул')
            self.assertTrue(item['topic_queue']);self.assertIn('pool',item['suggestions'])
            p={'kind':'name_occurrence','key':item['key'],'decision':'yes','value':'','revision':item['revision'],'request_id':'synthetic_topic_feedback_001'}
            with self.assertRaises(review.ReviewError):review.save_feedback(root,p)
            p.update(decision='custom',value='pull');self.assertTrue(review.save_feedback(root,p)['saved'])
            self.assertEqual(review.name_list(root,canonical='Linux')['total'],1)
            c=sqlite3.connect(root/bank.DB_NAME)
            try:self.assertEqual(c.execute('select value from feedback where request_id=?',(p['request_id'],)).fetchone()[0],'pull')
            finally:c.close()
    def test_long_close_name_not_general_rewrite(self):
        self.assertIn('contributor',terms.suggestions('contributer','Разработка'))
        self.assertFalse(terms.suggestions('controller','Разработка'))
        self.assertFalse(terms.suggestions('ordinary','Linux'))
if __name__=='__main__':unittest.main(verbosity=2)
