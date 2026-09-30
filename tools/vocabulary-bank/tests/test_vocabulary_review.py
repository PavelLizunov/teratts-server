import fcntl
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import vocabulary_bank as bank
import vocabulary_review as review
from voice_corpus import Corpus


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/"corpus"
        self.corpus=Corpus(self.root,min_free_bytes=0)
        self.sid=self.corpus.save(b"RIFF test audio",{"kind":"stt","raw_text":"Hello Omarchy","final_text":"Hello Omarchy"})
        self.corpus.save_record({"kind":"vocabulary_teacher_record","primary_text":"на Умрчи","teacher_text":"на Omarchy","vocabulary_hints":["Omarchy"],"original_sample_id":self.sid})
        bank.collect(self.root,idle_seconds=0)
    def tearDown(self):self.temp.cleanup()
    def payload(self,kind="term",decision="confirm"):
        row=review.term_list(self.root,"hello")["items"][0] if kind=="term" else review.dispute_list(self.root)["items"][0]
        return {"kind":kind,"key":row["key"],"decision":decision,"revision":row["revision"],"value":"","request_id":"synthetic_feedback_id_0001"}
    def test_conservative_alignment_and_character_ranges(self):
        result=review.dispute_alignment("Я говорю об Умрчи сейчас.","Я говорю об Omarchy сейчас.","Умрчи","Omarchy")
        self.assertTrue(result["reliable"])
        a,b=result["primary_range"];self.assertEqual("Я говорю об Умрчи сейчас."[a:b],"Умрчи")
        for primary,teacher,left,right in [
            ("слово тут слово там","слово здесь слово там","слово","слово"),
            ("сначала альфа потом бета","сначала бета потом альфа","альфа","бета"),
            ("Но есть проблемы","no hay problema","Но есть проблемы","no hay problema"),
            ("","текст","","текст")]:
            self.assertFalse(review.dispute_alignment(primary,teacher,left,right)["reliable"])
        insert=review.dispute_alignment("я хочу продолжить поиск","я хочу ну продолжить поиск","","ну")
        self.assertTrue(insert["reliable"]);self.assertEqual(insert["primary_range"][0],insert["primary_range"][1])

    def test_unreliable_pair_rejects_fragment_choice(self):
        self.corpus.save_record({"kind":"vocabulary_teacher_record","primary_text":"Но есть проблемы?","teacher_text":"no hay problema.","original_sample_id":self.sid})
        bank.collect(self.root,idle_seconds=0)
        row=next(r for r in review.dispute_list(self.root)["items"] if r["primary"]=="Но есть проблемы")
        self.assertFalse(row["alignment"]["reliable"])
        payload={"kind":"dispute","key":row["key"],"decision":"teacher","revision":row["revision"],"value":"","request_id":"synthetic_unaligned_001"}
        with self.assertRaises(review.ReviewError) as e:review.save_feedback(self.root,payload)
        self.assertEqual(e.exception.status,409)
        payload["decision"]="sentence_teacher"
        self.assertTrue(review.save_feedback(self.root,payload)["saved"])
        c=sqlite3.connect(self.root/bank.DB_NAME)
        try:self.assertEqual(json.loads(c.execute("SELECT context_json FROM feedback_context WHERE request_id=?",(payload["request_id"],)).fetchone()[0])["scope"],"sentence")
        finally:c.close()

    def test_live_data_search_audio(self):
        self.assertGreater(review.summary(self.root)["unique_terms"],3)
        data=review.dispute_list(self.root)
        self.assertEqual(data["total"],1);self.assertEqual(data["items"][0]["context_primary"],"на Умрчи")
        self.assertTrue(data["items"][0]["audio_available"])
        self.assertEqual(review.audio_bytes(self.root,self.sid),b"RIFF test audio")
        with self.assertRaises(review.ReviewError):review.audio_bytes(self.root,"../../etc/passwd")
    def test_persistent_confirmation_and_idempotency(self):
        payload=self.payload();first=review.save_feedback(self.root,payload)
        self.assertTrue(first["saved"]);self.assertFalse(first["training_approved"])
        self.assertTrue(review.save_feedback(self.root,payload)["duplicate"])
        self.assertEqual(review.summary(self.root)["feedback_count"],1)
        self.assertTrue(review.term_list(self.root,"hello")["items"][0]["confirmed"])
        payload["decision"]="reject"
        with self.assertRaises(review.ReviewError):review.save_feedback(self.root,payload)
    def test_stale_and_custom_validation(self):
        payload=self.payload();payload["revision"]="old"
        with self.assertRaises(review.ReviewError) as e:review.save_feedback(self.root,payload)
        self.assertEqual(e.exception.status,409)
        payload=self.payload();payload.update(decision="custom",value="")
        with self.assertRaises(review.ReviewError):review.save_feedback(self.root,payload)
    def test_seed_rejection_survives_collector(self):
        row=review.term_list(self.root,"omarchy")["items"][0]
        payload={"kind":"term","key":row["key"],"decision":"reject","revision":row["revision"],"value":"","request_id":"synthetic_seed_reject_001"}
        review.save_feedback(self.root,payload)
        bank.collect(self.root,idle_seconds=0)
        self.assertFalse(review.term_list(self.root,"omarchy")["items"][0]["confirmed"])

    def test_dispute_choice_not_global_confirmation(self):
        before=review.summary(self.root)["confirmed_terms"]
        result=review.save_feedback(self.root,self.payload("dispute","sentence_teacher"))
        self.assertFalse(result["autocorrection"])
        self.assertEqual(review.summary(self.root)["confirmed_terms"],before)
        self.assertEqual(review.dispute_list(self.root)["total"],0)
        self.assertEqual(review.dispute_list(self.root,pending=False)["total"],1)
    def test_lock_and_quota(self):
        payload=self.payload();fd=os.open(self.root/".lock",os.O_RDWR)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX)
            with self.assertRaises(review.ReviewError) as e:review.save_feedback(self.root,payload)
            self.assertEqual(e.exception.status,409)
        finally:os.close(fd)
        with patch.object(review,"MAX_BYTES",10):
            with self.assertRaises(review.ReviewError) as e:review.save_feedback(self.root,payload)
            self.assertEqual(e.exception.status,507)
        self.assertEqual(review.summary(self.root)["feedback_count"],0)
    def test_http_boundary_csrf_assets_and_feedback(self):
        server=ThreadingHTTPServer(("127.0.0.1",0),review.Handler)
        server.root=self.root;server.assets=ROOT/"review-ui"
        server.csrf=secrets.token_urlsafe(32);server.test_peers={"127.0.0.1"};server.hosts={f"127.0.0.1:{server.server_port}"}
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f"http://127.0.0.1:{server.server_port}"
        try:
            with urllib.request.urlopen(base+"/") as r:
                self.assertIn("Что мы услышали",r.read().decode());self.assertIn("frame-ancestors",r.headers["Content-Security-Policy"])
            payload=json.dumps(self.payload()).encode()
            req=urllib.request.Request(base+"/api/feedback",data=payload,headers={"Content-Type":"application/json"})
            with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(req)
            self.assertEqual(e.exception.code,403)
            req=urllib.request.Request(base+"/api/feedback",data=payload,headers={"Content-Type":"application/json","Origin":base,"X-CSRF-Token":server.csrf})
            with urllib.request.urlopen(req) as r:self.assertTrue(json.load(r)["saved"])
            req=urllib.request.Request(base+"/api/status",headers={"Host":"evil.example"})
            with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(req)
            server.test_peers=set()
            with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(base+"/api/status")
        finally:server.shutdown();server.server_close();thread.join()

if __name__=="__main__":unittest.main(verbosity=2)
