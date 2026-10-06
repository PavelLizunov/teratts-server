import io
from pathlib import Path
import sys
import tempfile
import unittest
import wave
import threading
import urllib.request
import urllib.error
import json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from gigaam_multilingual_server import pcm_from_wav,handler,METADATA,MAX_BYTES
from http.server import ThreadingHTTPServer

class Tests(unittest.TestCase):
 def wav(self,rate=16000,channels=1):
  buf=io.BytesIO()
  with wave.open(buf,'wb') as w:w.setnchannels(channels);w.setsampwidth(2);w.setframerate(rate);w.writeframes(b'\0\0'*rate*channels)
  return buf.getvalue()
 def test_pcm_validation_and_resample(self):
  self.assertEqual(len(pcm_from_wav(self.wav(8000,2))),16000)
  with self.assertRaises((ValueError,wave.Error,EOFError)):pcm_from_wav(b'bad')
  with self.assertRaises(ValueError):pcm_from_wav(self.wav(1000))
 def test_loopback_contract_and_limits(self):
  class Stub:
   ready=True
   def transcribe(self,raw):pcm_from_wav(raw);return {'text':'ее проверь','model':METADATA}
  server=ThreadingHTTPServer(('127.0.0.1',0),handler(Stub()));t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
  try:
   url='http://127.0.0.1:'+str(server.server_port)
   with urllib.request.urlopen(url+'/ready') as r:self.assertEqual(json.load(r)['model']['variant'],'multilingual_large_ctc')
   req=urllib.request.Request(url+'/transcribe',data=self.wav(),headers={'Content-Type':'audio/wav'})
   with urllib.request.urlopen(req) as r:self.assertEqual(json.load(r)['text'],'ее проверь')
   for data,ctype,status in [(b'bad','audio/wav',400),(b'a','text/plain',415)]:
    with self.assertRaises(urllib.error.HTTPError) as cm:urllib.request.urlopen(urllib.request.Request(url+'/transcribe',data=data,headers={'Content-Type':ctype}))
    self.assertEqual(cm.exception.code,status)
  finally:server.shutdown();server.server_close();t.join()
if __name__=='__main__':unittest.main(verbosity=2)
