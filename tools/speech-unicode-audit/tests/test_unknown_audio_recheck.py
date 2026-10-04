from pathlib import Path
import sys
import tempfile
import unittest
import io
import wave
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from recheck_unknown_audio import load_clip,UNKNOWN_IDS,YO_IDS
from voice_corpus import Corpus

class Tests(unittest.TestCase):
    def test_selection_controls_and_path_safety(self):
        self.assertEqual(len(UNKNOWN_IDS),3);self.assertEqual(len(YO_IDS),2)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):load_clip(tmp,'../../secret')
    def test_exact_audio_hash_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'c';corpus=Corpus(root,min_free_bytes=0);buf=io.BytesIO()
            with wave.open(buf,'wb') as wav:wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(b'\x01\0'*16000)
            sid=corpus.save(buf.getvalue(),{'kind':'stt','raw_text':'е<unk>','final_text':'е<unk>','model_sha256':'known'})
            audio,data=load_clip(root,sid)
            self.assertEqual(audio,buf.getvalue());self.assertEqual(data['duration_s'],1)
            self.assertEqual(data['recorded_ultra_raw'],'е<unk>')
            self.assertEqual(data['recorded_final'],'е<unk>')
            self.assertEqual(data['source_model_sha'],'known')
    def test_no_production_switch_or_hint_prompt(self):
        source=(ROOT/'recheck_unknown_audio.py').read_text()
        self.assertNotIn('--speech-context',source)
        self.assertNotIn('systemctl restart',source)
        self.assertIn("'--device','cpu'",source)
if __name__=='__main__':unittest.main(verbosity=2)
