"""Finite five-clip CPU rerecognition, no hints/production changes/cloud calls."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import time
import tarfile
import wave

UNKNOWN_IDS=['01791115333651808476-e60a49af5196402e9fe0f461038ce21c','01791115841185451273-dafe1c0420114021b3bc116cd674db37','01791136394253647186-46b85e165a9444e2a8fabf2878d017c8']
YO_IDS=['01791136466785858645-29e49935743d4c3eabe53ada0c57dc65','01791136472979803381-555ca7eff93b43e48d3627154db4a580']
MODELS={
 'nemotron':('/home/deck/homelab/nemotron-pilot/models/ea30d66debe3740a08b573244286791d423d6b3e/nemotron.q8_0.gguf','3fc991d3badad7277c11030a7519832cddaf2057aafed6d4b25147e953a070b1'),
 'parakeet_v3':('/home/deck/homelab/parakeet-trial/models/nvidia/parakeet-tdt-0.6b-v3/541d1f99c6b0c3cd0b11a95167540bb8edefd82b/parakeet-tdt-0.6b-v3.q8_0.gguf','e3880d0aaaaf2c308ea2c35016b2b895c423eb3fda924c1b463d1c19b7f4d32e')}
CLI='/home/deck/homelab/parakeet-trial/nemo-speech-0.1.0-linux-x86_64-vulkan/bin/nemo-speech'


def load_clip(corpus,sid):
 if not re.fullmatch('[0-9]{20}-[a-f0-9]{32}',sid):raise ValueError('Invalid source ID')
 path=Path(corpus)/(sid+'.tar')
 if path.is_symlink():raise ValueError('Symlink refused')
 with tarfile.open(path) as archive:
  member=archive.getmember('sample.json');assert member.isfile() and member.size<=1048576
  meta=json.load(archive.extractfile(member));assert meta['kind']=='stt' and meta['sample_id']==sid
  member=archive.getmember('original.wav');assert member.isfile() and member.size<=10*1024*1024
  audio=archive.extractfile(member).read()
 digest=hashlib.sha256(audio).hexdigest()
 if digest!=meta['audio_sha256']:raise ValueError('Source WAV hash differs')
 with wave.open(io.BytesIO(audio)) as wav:
  if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())!=(1,2,16000):raise ValueError('Unsupported control WAV')
  frames=wav.getnframes();duration=frames/16000
  if not 0<duration<=25 or len(wav.readframes(frames))!=frames*2:raise ValueError('Invalid bounded audio')
 return audio,{'sample_id':sid,'audio_sha256':digest,'duration_s':duration,'recorded_ultra_raw':meta['raw_text'],'recorded_final':meta['final_text'],'source_model_sha':meta.get('model_sha256'),'kind':'unknown_case' if sid in UNKNOWN_IDS else 'letter_control'}


def run(root,corpus):
 root=Path(root);root.mkdir(mode=0o700,exist_ok=True);os.chmod(root,0o700)
 clips=[]
 for i,sid in enumerate(UNKNOWN_IDS+YO_IDS,1):
  audio,metadata=load_clip(corpus,sid);path=root/f'clip-{i}.wav'
  if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()!=metadata['audio_sha256']:raise ValueError('Frozen clip changed')
  if not path.exists():path.write_bytes(audio);path.chmod(0o600)
  clips.append({**metadata,'file':path.name})
 if sum(c['duration_s'] for c in clips)>45:raise ValueError('Scope exceeded')
 manifest={'clips':clips,'hints':[],'device':'cpu','language':'ru','gold_reference':False}
 p=root/'manifest.json'
 if p.exists() and json.loads(p.read_text())!=manifest:raise ValueError('Recheck input changed')
 if not p.exists():p.write_text(json.dumps(manifest,ensure_ascii=False,indent=2));p.chmod(0o600)
 for model,(path,expected) in MODELS.items():
  with Path(path).open('rb') as stream:
   if hashlib.file_digest(stream,'sha256').hexdigest()!=expected:raise ValueError('Model changed')
  for i,clip in enumerate(clips,1):
   output=root/f'{model}-{i}.asr.json';record=root/f'{model}-{i}.record.json';marker=root/f'{model}-{i}.started'
   if record.exists():continue
   if marker.exists():raise ValueError('Prior ambiguous dispatch; no automatic retry')
   marker.write_text(str(time.time()));marker.chmod(0o600)
   cmd=[CLI,'transcribe',str(root/clip['file']),'--model',path,'--device','cpu','--language','ru','--format','json','--output',str(output),'--no-warmup','--no-batching']
   start=time.monotonic();answer=subprocess.run(cmd,capture_output=True,text=True,timeout=90)
   result=json.loads(output.read_text()) if answer.returncode==0 and output.exists() else None
   row={**clip,'comparison_model':model,'model_sha256':expected,'device':'cpu','hints':[],
        'returncode':answer.returncode,'cold_cli_seconds':round(time.monotonic()-start,3),
        'result':result,'diagnostic_tail':answer.stderr[-2000:],'human_gold':False,'transcript_hypothesis_only':True}
   record.write_text(json.dumps(row,ensure_ascii=False,indent=2));record.chmod(0o600)
   print(json.dumps({'model':model,'clip':i,'returncode':answer.returncode,'text_characters':len((result or {}).get('text','')),'seconds':row['cold_cli_seconds']}),flush=True)
   if answer.returncode!=0:raise RuntimeError('Recheck stopped after explicit failure')

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--corpus',type=Path,required=True);a=p.parse_args();run(a.root,a.corpus)
