"""Thin adapter to upstream transcribe.cpp model/session, no new inference engine."""
import hashlib
from pathlib import Path
import threading
import numpy as np

import transcribe_cpp


class UltraASR:
    def __init__(self,path,expected_sha256,backend='vulkan'):
        path=Path(path)
        with path.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=expected_sha256:
                raise ValueError('Ultra model identity changed')
        self.model=transcribe_cpp.Model(path,backend=backend)
        if self.model.variant!='tdt-0.6b-ultra' or self.model.arch!='parakeet':
            self.model.close();raise ValueError('Wrong loaded model family/variant')
        self.session=self.model.session(n_threads=1)
        self.lock=threading.Lock()
        self.ready=True
        self.metadata={'model':'moondream/parakeet-ultra',
            'model_revision':'73175eb7aeb0d82f1e2a6b53b3aabc10a90bcd0b',
            'artifact_repo':'Nairod785/parakeet-ultra-gguf',
            'artifact_revision':'b03613ba54a195238f0e915359f5a5c78269ddc6',
            'model_sha256':expected_sha256,'quantization':'Q8_0',
            'engine':'transcribe.cpp','engine_version':'0.2.4','device':self.model.backend,
            'variant':self.model.variant}

    def transcribe(self,pcm,sample_rate=16000):
        pcm=np.asarray(pcm,dtype=np.float32)
        if sample_rate<8000 or sample_rate>96000 or pcm.ndim!=1 or not np.isfinite(pcm).all():
            raise ValueError('Unsupported source PCM')
        if sample_rate!=16000 and len(pcm):
            target=max(1,round(len(pcm)*16000/sample_rate))
            pcm=np.interp(np.arange(target)*sample_rate/16000,np.arange(len(pcm)),pcm).astype(np.float32)
        with self.lock:
            if not self.ready:raise RuntimeError('Ultra is unavailable')
            return self.session.run(pcm,language='ru',timestamps='none').text

    def close(self):
        with self.lock:
            if not self.ready:return
            self.ready=False
            self.session.close();self.model.close()
