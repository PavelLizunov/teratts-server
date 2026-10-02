"""Finite compatible Ultra smoke, no production routing/model changes."""
import argparse
import io
import json
from pathlib import Path
import time
import wave
import numpy as np
import transcribe_cpp

p=argparse.ArgumentParser();p.add_argument('--backend',choices=['cpu','vulkan'],default='cpu');p.add_argument('--output',required=True)
a=p.parse_args();root=Path('/home/deck/homelab/ultra-upgrade')
model=transcribe_cpp.Model(root/'models/parakeet-ultra-Q8.gguf',backend=a.backend)
session=model.session(n_threads=1);results=[]
for wav_path in [Path('/home/deck/homelab/nemotron-pilot/samples/1.wav'),Path('/home/deck/homelab/nemotron-pilot/samples/3.wav'),Path('/home/deck/homelab/nemotron-pilot/silence.wav')]:
 with wave.open(str(wav_path)) as w:
  assert w.getframerate()==16000 and w.getnchannels()==1 and w.getsampwidth()==2
  pcm=np.frombuffer(w.readframes(w.getnframes()),dtype=np.int16).astype(np.float32)/32768
  duration=len(pcm)/16000
 start=time.perf_counter();result=session.run(pcm,language='ru',timestamps='none');elapsed=(time.perf_counter()-start)*1000
 results.append({'file':str(wav_path),'audio_s':duration,'text':result.text,'elapsed_ms':round(elapsed,2)})
print('COMPATIBLE_ULTRA_RESULTS',json.dumps({'backend':model.backend,'arch':model.arch,'variant':model.variant,'results':results},ensure_ascii=False))
Path(a.output).write_text(json.dumps({'backend':model.backend,'arch':model.arch,'variant':model.variant,'results':results},ensure_ascii=False,indent=2));Path(a.output).chmod(0o600)
session.close();model.close()
