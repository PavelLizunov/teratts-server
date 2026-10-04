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
  self.assertIn("'initial_prompt':None",src);self.assertIn("device='cpu'",src);self.assertIn('weights_only=True',src);self.assertIn('sys.addaudithook(prohibit_network)',src)
  self.assertIn("model.transcribe(pcm,**params)",src)
 def test_pair_collection_and_stable_balanced_blinding(self):
  from collect_dual_asr_results import collect
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);m={'records':[{'sample_id':str(i),'audio_sha256':str(i),'duration_s':1,'category':'negative_control' if i>=16 else 'real'} for i in range(18)]}
   atomic(root/'manifest-private.json',m);digest=hashlib.sha256((root/'manifest-private.json').read_bytes()).hexdigest()
   for name in ['whisper','gigaam']:
    d=root/'results'/name;d.mkdir(parents=True)
    atomic(d/'complete.json',{'complete':True,'results':18,'manifest_sha256':digest})
    atomic(d/'runtime.json',{'load_seconds':1})
    for i,source in enumerate(m['records'],1):atomic(d/f'{i:02d}.json',{**source,'success':True,'no_hints':True,'manifest_sha256':digest,'text':name+str(i),'seconds':1})
   report,pairs=collect(root);_,again=collect(root)
   self.assertEqual(pairs,again);self.assertEqual(report['paired_results'],36)
   self.assertEqual(sum(p['option1_text'].startswith('whisper') for p in pairs),8)
   self.assertNotIn('model',pairs[0]);self.assertEqual(len(pairs),16)
if __name__=='__main__':unittest.main(verbosity=2)
