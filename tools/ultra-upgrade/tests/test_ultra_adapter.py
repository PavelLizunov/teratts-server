import importlib.util
from pathlib import Path
import hashlib
import sys
import tempfile
import threading
import types
import unittest
import numpy as np
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]

class Tests(unittest.TestCase):
    def test_identity_lock_and_close(self):
        sessions=[]
        class Session:
            closed=False
            def run(self,pcm,**kwargs):self.kwargs=kwargs;self.pcm=pcm;return types.SimpleNamespace(text='result')
            def close(self):self.closed=True
        class Model:
            variant='tdt-0.6b-ultra';arch='parakeet';backend='VULKAN';closed=False
            def __init__(self,path,backend):self.path=path
            def session(self,n_threads):self.n_threads=n_threads;s=Session();sessions.append(s);return s
            def close(self):self.closed=True
        with patch.dict(sys.modules,{'transcribe_cpp':types.SimpleNamespace(Model=Model)}):
            spec=importlib.util.spec_from_file_location('adapter',ROOT/'ultra_asr.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            with tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp)/'model';p.write_bytes(b'fixture');sha=hashlib.sha256(p.read_bytes()).hexdigest()
                with self.assertRaises(ValueError):module.UltraASR(p,'bad')
                instance=module.UltraASR(p,sha)
                self.assertEqual(instance.transcribe([0]),'result');self.assertEqual(sessions[0].kwargs,{'language':'ru','timestamps':'none'})
                self.assertEqual(instance.metadata['engine_version'],'0.2.4');self.assertEqual(instance.model.n_threads,1)
                instance.transcribe(np.ones(8000,dtype=np.float32),sample_rate=8000)
                self.assertEqual(len(sessions[0].pcm),16000)
                with self.assertRaises(ValueError):instance.transcribe([float('nan')])
                instance.close();instance.close();self.assertTrue(sessions[0].closed)
                with self.assertRaises(RuntimeError):instance.transcribe([0])
    def test_wrong_variant_refused(self):
        class Model:
            variant='base';arch='parakeet'
            def __init__(self,*args,**kwargs):pass
            def close(self):pass
        with patch.dict(sys.modules,{'transcribe_cpp':types.SimpleNamespace(Model=Model)}):
            spec=importlib.util.spec_from_file_location('adapter2',ROOT/'ultra_asr.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            with tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp)/'m';p.write_bytes(b'x')
                with self.assertRaises(ValueError):module.UltraASR(p,hashlib.sha256(b'x').hexdigest())
if __name__=='__main__':unittest.main(verbosity=2)
