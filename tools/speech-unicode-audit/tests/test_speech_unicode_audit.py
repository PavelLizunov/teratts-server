import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import wave
import struct
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from audit_speech_unicode import suspicious,audit
from voice_corpus import Corpus

class Tests(unittest.TestCase):
    def test_normal_yo_not_flagged_and_special_unicode_is(self):
        for ch in ['ё','Ё','е','Я','\n']:self.assertFalse(suspicious(ch))
        for ch in ['\ufffd','і','č','\u0308','\u200b']:self.assertTrue(suspicious(ch))
    def test_stage_origin_and_wav_hash_readonly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'c';corpus=Corpus(root,min_free_bytes=0);buf=io.BytesIO()
            with wave.open(buf,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0\0'*16000)
            corpus.save(buf.getvalue(),{'kind':'stt','backend':'ultra','raw_text':'е<unk> ещё і','final_text':'е<unk> ещё і'})
            paths={p.name:p.read_bytes() for p in root.glob('*.tar')}
            result=audit(root,48)
            self.assertEqual(result['recent_special_tokens'],{'ultra:<unk>':1})
            self.assertEqual(result['recent_stt_counts']['raw_normal_yo'],1)
            self.assertTrue(result['audio_checks'][0]['hash_ok']);self.assertFalse(result['errors'])
            self.assertEqual(paths,{p.name:p.read_bytes() for p in root.glob('*.tar')})
    def test_bounded_actual_gguf_metadata_parser(self):
        from inspect_gguf_speech_tokens import inspect
        def s(text):
            b=text.encode();return struct.pack('<Q',len(b))+b
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'test.gguf'
            content=b'GGUF'+struct.pack('<IQQ',3,0,2)
            content+=s('tokenizer.ggml.tokens')+struct.pack('<IIQ',9,8,3)+s('<unk>')+s('е')+s('ж')
            content+=s('tokenizer.ggml.token_type')+struct.pack('<IIQiii',9,5,3,2,1,1)
            p.write_bytes(content);result=inspect(p)
            self.assertEqual(result['unknown_tokens'][0],{'id':0,'token':'<unk>','type':2})
            self.assertFalse(result['literal_yo_tokens']);self.assertTrue(result['no_weights_loaded'])
            p.write_bytes(b'bad')
            with self.assertRaises(ValueError):inspect(p)
if __name__=='__main__':unittest.main(verbosity=2)
