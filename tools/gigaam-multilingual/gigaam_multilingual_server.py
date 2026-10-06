"""Loopback-only adapter to pinned official GigaAM classes. No cloud/lexical hints."""
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEIGHTS_SHA='c3fabefb50b41f08f4d7ad44e02c26c37d242882704cdcca2ebd98e45eff73d1'
SOURCE_SHA='6d02e640fbb5738ab11c030520a68654ef32f4ff363723db10534cf8b5d5c0e7'
CONFIG_SHA='5ea1089c77b60e094352d7fb7bfb6580906b380c4dc7053edb4f7f0a1f59c172'
METADATA={'model':'ai-sage/GigaAM-Multilingual','model_revision':'3905cd51c3ed4e88c8edf33f3302969ba480a327',
 'model_sha256':WEIGHTS_SHA,'quantization':'none','variant':'multilingual_large_ctc',
 'engine':'pytorch','engine_version':'2.10.0+cpu','device':'cpu','dtype':'float32','decoder':'CTC greedy','punctuation':'none',
 'chunk_max_seconds':25,'chunk_cut':'quietest 160ms window in last4sec,continuous nonoverlap'}
MAX_BYTES=10*1024*1024


def pcm_from_wav(raw):
 import numpy as np
 with wave.open(io.BytesIO(raw)) as wav:
  channels,width,rate,frames=wav.getnchannels(),wav.getsampwidth(),wav.getframerate(),wav.getnframes()
  if channels not in [1,2] or width!=2 or not 8000<=rate<=96000 or frames<=0:raise ValueError('Unsupported WAV: PCM16 mono/stereo 8-96kHz required')
  data=wav.readframes(frames)
  if len(data)!=frames*channels*width:raise ValueError('Truncated audio')
  pcm=np.frombuffer(data,dtype='<i2').astype(np.float32)/32768
  if channels>1:pcm=pcm.reshape(-1,channels).mean(axis=1)
  if rate!=16000:
   target=max(1,round(len(pcm)*16000/rate));pcm=np.interp(np.arange(target)*rate/16000,np.arange(len(pcm)),pcm).astype(np.float32)
 if not np.isfinite(pcm).all():raise ValueError('Non-finite audio')
 return pcm


class Recognizer:
 def __init__(self,root):
  root=Path(root)
  for name,sha in [('pytorch_model.bin',WEIGHTS_SHA),('modeling_gigaam.py',SOURCE_SHA),('config.json',CONFIG_SHA)]:
   with (root/name).open('rb') as stream:
    if hashlib.file_digest(stream,'sha256').hexdigest()!=sha:raise ValueError('Pinned artifact changed: '+name)
  import torch
  if torch.__version__!='2.10.0+cpu' or torch.version.cuda is not None:raise ValueError('Wrong CPU Torch runtime')
  torch.set_num_threads(2);torch.set_num_interop_threads(1)
  spec=importlib.util.spec_from_file_location('modeling_gigaam',root/'modeling_gigaam.py')
  module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
  config=module.GigaAMConfig.from_pretrained(str(root),local_files_only=True)
  self.model=module.GigaAMModel.from_pretrained(str(root),config=config,local_files_only=True,use_safetensors=False,dtype=torch.float32,weights_only=True).to('cpu').eval()
  self.torch=torch;self.lock=threading.Lock();self.ready=True

 def transcribe(self,raw):
  pcm=pcm_from_wav(raw)
  if not self.lock.acquire(blocking=False):raise BlockingIOError('Decoder busy')
  try:
   import numpy as np
   # Bounded memory for long submitted audio. End each chunk at quietest 160ms
   # window in last four seconds, no overlap/duplicate text or audio omission.
   segments=[];start=0;limit=25*16000
   with self.torch.inference_mode():
    while start<len(pcm):
     end=min(start+limit,len(pcm))
     if end<len(pcm):
      first=end-4*16000;window=2560
      candidates=list(range(first,end-window+1,window))
      cut=min(candidates,key=lambda pos:float(np.mean(pcm[pos:pos+window]**2)))
      end=cut+window//2
     chunk=pcm[start:end];wav=self.torch.from_numpy(chunk).unsqueeze(0);length=self.torch.tensor([len(chunk)],dtype=self.torch.long)
     encoded,encoded_len=self.model.model.forward(wav,length)
     text,_=self.model.model._decode(encoded,encoded_len,length,False)[0]
     segments.append({'start_s':start/16000,'end_s':end/16000,'text':text});start=end
   return {'text':' '.join(s['text'].strip() for s in segments if s['text'].strip()),'segments':segments,'model':METADATA,'audio_duration_s':len(pcm)/16000}
  finally:self.lock.release()


def handler(recognizer):
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def setup(self):super().setup();self.connection.settimeout(30)
  def send_json(self,status,data):
   encoded=json.dumps(data,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
  def do_GET(self):
   if self.path!='/ready':return self.send_json(404,{'error':'not found'})
   self.send_json(200,{'ready':recognizer.ready,'model':METADATA})
  def do_POST(self):
   if self.path!='/transcribe':return self.send_json(404,{'error':'not found'})
   try:
    length=int(self.headers.get('Content-Length','0'))
    if not 0<length<=MAX_BYTES:return self.send_json(413,{'error':'WAV size limit'})
    if self.headers.get('Content-Type')!='audio/wav':return self.send_json(415,{'error':'audio/wav required'})
    raw=self.rfile.read(length)
    if len(raw)!=length:raise ValueError('Short request')
    start=time.perf_counter();result=recognizer.transcribe(raw);result['inference_ms']=(time.perf_counter()-start)*1000
    self.send_json(200,result)
   except (ValueError,wave.Error,EOFError):self.send_json(400,{'error':'Invalid or unsupported WAV'})
   except BlockingIOError:self.send_json(503,{'error':'Decoder busy'})
   except (BrokenPipeError,ConnectionResetError,socket.timeout):pass
   except Exception:self.send_json(503,{'error':'Decoder failure'})
 return Handler

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--model-dir',required=True);p.add_argument('--port',type=int,default=10002);a=p.parse_args()
 recognizer=Recognizer(a.model_dir)
 # Deny Python internet connects after imports/weights. Local HTTPServer binds below.
 def audit(event,args):
  if event=='socket.connect':raise RuntimeError('ASR does not make outbound connections')
 sys.addaudithook(audit)
 server=ThreadingHTTPServer(('127.0.0.1',a.port),handler(recognizer));server.daemon_threads=True
 print(json.dumps({'ready':True,'model':METADATA}),flush=True);server.serve_forever()
