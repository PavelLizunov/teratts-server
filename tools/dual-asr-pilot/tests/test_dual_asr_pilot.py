import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import wave
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from run_dual_asr_pilot import atomic,validate
from select_dual_asr_clips import source
from voice_corpus import Corpus

class Tests(unittest.TestCase):
 def wav(self):
  buf=io.BytesIO()
  with wave.open(buf,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0\0'*16000)
  return buf.getvalue()
 def test_source_hash_real_only(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'corpus';c=Corpus(root,min_free_bytes=0)
   sid=c.save(self.wav(),{'kind':'stt','backend':'parakeet','raw_text':'GitHub','client_context':{'headers':{'x-request-id':'human'}}})
   row=source(root/(sid+'.tar'));self.assertEqual(row['audio_sha256'],hashlib.sha256(self.wav()).hexdigest())
   sid=c.save(self.wav(),{'kind':'stt','raw_text':'test','client_context':{'headers':{'x-request-id':'synthetic-fixture'}}})
   self.assertIsNone(source(root/(sid+'.tar')))
 def test_manifest_integrity_and_unsafe_path(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);audio=root/'dual-asr-snapshot-20261004';audio.mkdir();(audio/'test.wav').write_bytes(self.wav())
   rows=[]
   for i in range(18):
    audio_bytes=self.wav()+str(i).encode();file=f'{i}.wav';(audio/file).write_bytes(audio_bytes)
    rows.append({'file':file,'audio_sha256':hashlib.sha256(audio_bytes).hexdigest(),'category':'negative_control' if i>=16 else 'real'})
   m={'records':rows,'real_clips':16,'real_audio_seconds':16}
   atomic(audio/'manifest.json',m);(audio/'manifest.sha256').write_text(hashlib.sha256((audio/'manifest.json').read_bytes()).hexdigest())
   (root/'models').mkdir();(root/'models/verified-artifacts.json').write_text('[]')
   self.assertEqual(len(validate(root)[0]['records']),18)
   m['records'][0]['file']='../bad';atomic(audio/'manifest.json',m);(audio/'manifest.sha256').write_text(hashlib.sha256((audio/'manifest.json').read_bytes()).hexdigest())
   with self.assertRaises(ValueError):validate(root)
 def test_output_private_atomic_and_no_prompt(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'result.json';atomic(p,{'text':'проверка'})
   self.assertEqual(p.stat().st_mode&0o777,0o600);self.assertFalse(p.with_suffix('.json.part').exists())
  src=(ROOT/'run_dual_asr_pilot.py').read_text()
  self.assertIn("'initial_prompt':None",src);self.assertIn("device='cpu'",src);self.assertIn('weights_only=True',src)
if __name__=='__main__':unittest.main(verbosity=2)
