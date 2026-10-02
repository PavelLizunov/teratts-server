from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import blind_challenge_set as challenge
import model_comparison_review as model
import vocabulary_review as review
import vocabulary_bank as bank
from voice_corpus import Corpus


def data(n=60):
    rows=[]
    for i in range(n):
        a=f'Задача номер {i} открой GitHub потом проверь все файлы и отправь изменения в репозиторий без ошибок'
        b=f'Задача номер {i} открой терминал потом удали старые папки и сохрани документы в архив сейчас'
        rows.append({'audio_sha256':f'{i:064x}','status':'completed','candidate_text':b,'duration_s':8+i/10,
                     'comparisons':[{'sample_id':str(i),'baseline_raw':a,'same_normalized_text':False,'category':'substantial_difference','token_agreement_ratio':0.5}]})
    return {'all_manifest_results_successful':True,'model_sha256':model.MODEL_SHA,'frozen_manifest_sha256':model.MANIFEST_SHA,'total_unique_audio':n,'results':rows}

class Tests(unittest.TestCase):
    def test_features_skip_short_empty_punctuation_and_singleword(self):
        a='один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать'
        self.assertIsNone(challenge.features(a,a+'!',10))
        self.assertIsNone(challenge.features(a,'',10))
        self.assertIsNone(challenge.features(a,a.replace('один ','два ',1),10))
        self.assertIsNone(challenge.features(a,'совсем другой текст',1))
        f=challenge.features('Нужно открыть GitHub и проверить не меньше 12 файлов потом закрыть все процессы в системе',
                             'Нужно открыть архив и удалить больше 20 каталогов потом перезапустить все службы в системе',10)
        self.assertTrue(f['technical']);self.assertTrue(f['numbers']);self.assertTrue(f['negation'])
    def test_balanced_unreviewed_fixed_set_preserves_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'c';Corpus(root,min_free_bytes=0).status();c=bank.open_database(root)
            model.import_records(c,model.build_records(data()))
            assignments=c.execute('select * from blind_assignments order by token').fetchall()
            c.execute('CREATE TABLE feedback(request_id TEXT PRIMARY KEY,target_kind TEXT,target_key TEXT,decision TEXT,value TEXT,created_ns INTEGER)')
            reviewed=[r[0] for r in assignments[:10]]
            with c:
                for i,token in enumerate(reviewed):c.execute('insert into feedback values(?,?,?,?,?,?)',(f'old{i}','blind_comparison',token,'unsure','',i))
            result=challenge.install(c,30);self.assertEqual(result['selected'],30);self.assertTrue(result['balanced'])
            tokens=[r[0] for r in c.execute('select token from blind_review_sets')]
            self.assertFalse(set(tokens)&set(reviewed))
            self.assertEqual(assignments,c.execute('select * from blind_assignments order by token').fetchall())
            self.assertEqual(challenge.install(c)['status'],'already_fixed')
            c.close()
            public=review.blind_list(root,filter='challenge');self.assertEqual(public['total'],30)
            self.assertTrue(public['items'][0]['selection_reasons'])
            self.assertNotIn('option1_primary',public['items'][0])
    def test_even_size_and_no_duplicate_sentence(self):
        with self.assertRaises(ValueError):challenge.select(None,3)
if __name__=='__main__':unittest.main(verbosity=2)
