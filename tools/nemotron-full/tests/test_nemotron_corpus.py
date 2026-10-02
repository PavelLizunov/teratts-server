import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import wave
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import nemotron_corpus_snapshot as snapshot
import run_nemotron_corpus as runner
from voice_corpus import Corpus


def audio(seconds=1):
    buffer=io.BytesIO()
    with wave.open(buffer,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\x02\0'*(16000*seconds))
    return buffer.getvalue()

class Tests(unittest.TestCase):
    def test_all_empty_failed_and_duplicate_mapping(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);corpus=Corpus(root/'corpus',min_free_bytes=0);wav=audio()
            corpus.save(wav,{'kind':'stt','raw_text':'','final_text':''})
            corpus.save(wav,{'kind':'stt','raw_text':'text'})
            corpus.save_record({'kind':'stt_failure','status':503},{'original.bin':audio(2)})
            corpus.save_record({'kind':'stt_failure'},{'original.bin':b'not a wav'})
            corpus.save_record({'kind':'tts_http'},{'synthesized.wav':wav})
            corpus.save(wav,{'kind':'stt','raw_text':'test','client_context':{'headers':{'x-request-id':'synthetic-test'}}})
            out=root/'snapshot';summary=snapshot.snapshot(corpus.root,out)
            self.assertEqual(summary['eligible_sources'],3);self.assertEqual(summary['unique_audio'],2)
            self.assertEqual(summary['duplicate_sources'],1)
            self.assertEqual(summary['source_counts']['synthetic_control'],1)
            self.assertEqual(summary['source_counts']['invalid_or_unreadable'],1)
            manifest,digest=runner.validate_manifest(out)
            self.assertEqual(len(manifest['records'][0]['sources']),2)
            for row in manifest['records']:
                self.assertEqual(hashlib.sha256((out/row['file']).read_bytes()).hexdigest(),row['audio_sha256'])
                self.assertEqual((out/row['file']).stat().st_mode&0o777,0o600)
            with self.assertRaises(ValueError):snapshot.snapshot(corpus.root,out)
            (out/'manifest.json').write_text('{}')
            with self.assertRaises(ValueError):runner.validate_manifest(out)
    def test_truncated_and_stereo_valid(self):
        wav=audio();self.assertEqual(snapshot.wav_info(wav)['duration_s'],1)
        with self.assertRaises((ValueError,wave.Error,EOFError)):snapshot.wav_info(wav[:-100])
        with self.assertRaises((ValueError,wave.Error,EOFError)):snapshot.wav_info(b'bad')
    def test_http_exact_no_hints_and_transcript(self):
        seen=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=self.rfile.read(int(self.headers['Content-Length']));seen.append(body)
                result=json.dumps({'text':'test','duration':1}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(result)));self.end_headers();self.wfile.write(result)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            result=runner.transcribe(runner.urllib.request.build_opener(runner.urllib.request.ProxyHandler({})),f'http://127.0.0.1:{server.server_port}',audio(),5)
            self.assertEqual(result['text'],'test');self.assertIn(audio(),seen[0])
            self.assertNotIn(b'speech_context',seen[0]);self.assertIn(b'verbose_json',seen[0])
        finally:server.shutdown();server.server_close();thread.join()
    def test_progress_failed_not_silent_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            result=runner.progress(root,{'unique_audio':2},'sha',[{'status':'http_failure'}],finished=False)
            self.assertFalse(result['coverage_complete']);self.assertEqual(result['remaining'],1)
            self.assertFalse(result['gold_accuracy_measured'])
    def test_resume_preserves_started_unknown_without_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);corpus=Corpus(root/'corpus',min_free_bytes=0)
            corpus.save(audio(),{'kind':'stt','raw_text':'baseline'})
            out=root/'snapshot';snapshot.snapshot(corpus.root,out)
            manifest,digest=runner.validate_manifest(out);sha=manifest['records'][0]['audio_sha256']
            model=root/'model.gguf';model.write_bytes(b'synthetic model')
            expected=hashlib.sha256(model.read_bytes()).hexdigest()
            snapshot.atomic_json(out/'silence-control.json',{'passed_empty':True,'text':''})
            (out/'results').mkdir();snapshot.atomic_json(out/'results'/(sha+'.started.json'),{'manifest_sha256':digest})
            class Reply:
                def __enter__(self):return io.BytesIO(b'{"ready":true,"device":"cpu"}')
                def __exit__(self,*args):pass
            class Opener:
                def open(self,*args,**kwargs):return Reply()
            with patch.object(runner,'MODEL_SHA',expected),patch.object(runner.urllib.request,'build_opener',return_value=Opener()),patch.object(runner,'transcribe',side_effect=AssertionError('Must not redispatch')):
                runner.run(out,corpus.root,model,'http://127.0.0.1:10004')
                runner.run(out,corpus.root,model,'http://127.0.0.1:10004')
            result=json.loads((out/'results'/(sha+'.json')).read_text())
            self.assertEqual(result['status'],'interrupted_unknown_no_retry')
            self.assertTrue(json.loads((out/'progress.json').read_text())['coverage_complete'])
    def test_summary_disagreement_is_not_accuracy(self):
        from summarize_nemotron_corpus import disagreement,percentile
        self.assertEqual(disagreement('Ёлка, слово!','елка слово')['category'],'agreement')
        self.assertEqual(disagreement('пул','push')['category'],'substantial_difference')
        self.assertNotIn('wer',disagreement('a','b'))
        self.assertEqual(percentile([1,2,3],0.5),2)
    def test_invalid_manifest_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);data={'unique_audio':1,'records':[{'audio_sha256':'a'*64,'file':'../bad'}]}
            snapshot.atomic_json(root/'manifest.json',data)
            (root/'manifest.sha256').write_text(hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest())
            with self.assertRaises(ValueError):runner.validate_manifest(root)
if __name__=='__main__':unittest.main(verbosity=2)
