"""Read-only fixed small ASR trial selection, no cloud calls or re-transcription."""
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import wave

TECH=re.compile(r'чат|джи|gemini|github|г[ие]тх|omarchy|[ауо]марч|плаг|linux|контриб|пул|пуш|sudo|репозит',re.I)
UNKNOWN_IDS=['01791115333651808476-e60a49af5196402e9fe0f461038ce21c','01791115841185451273-dafe1c0420114021b3bc116cd674db37','01791136394253647186-46b85e165a9444e2a8fabf2878d017c8']


def source(path):
 with tarfile.open(path) as archive:
  m=json.load(archive.extractfile('sample.json'))
  if m.get('kind')!='stt':return None
  rid=m.get('client_context',{}).get('headers',{}).get('x-request-id','')
  if rid.startswith('synthetic'):return None
  member=archive.getmember('original.wav')
  if member.size>10*1024*1024:raise ValueError('Large audio')
  audio=archive.extractfile(member).read()
 sha=hashlib.sha256(audio).hexdigest()
 if sha!=m['audio_sha256']:raise ValueError('Hash mismatch')
 with wave.open(io.BytesIO(audio)) as w:
  if (w.getnchannels(),w.getsampwidth(),w.getframerate())!=(1,2,16000):return None
  duration=w.getnframes()/16000
  if len(w.readframes(w.getnframes()))!=w.getnframes()*2:raise ValueError('Truncated')
 return {'sample_id':m['sample_id'],'audio_sha256':sha,'duration_s':duration,'baseline_raw':m.get('raw_text',''),
         'baseline_backend':m.get('backend'),'collected_ns':m.get('collected_at_unix_ns',0),'audio':audio}


def choose(root):
 rows=[]
 for p in sorted(Path(root).glob('*.tar')):
  try:r=source(p)
  except (ValueError,KeyError,OSError,tarfile.TarError):continue
  if r:rows.append(r)
 selected=[];seen=set();seconds=0
 def add(r,category):
  nonlocal seconds
  if r['audio_sha256'] in seen or seconds+r['duration_s']>180:return False
  selected.append({**r,'category':category});seen.add(r['audio_sha256']);seconds+=r['duration_s'];return True
 for sid in UNKNOWN_IDS:
  row=next((r for r in rows if r['sample_id']==sid),None)
  if row:add(row,'unknown_marker')
 groups=[('technical',6,lambda r:3<=r['duration_s']<=15 and TECH.search(r['baseline_raw'])),
         ('plain_long',4,lambda r:8<=r['duration_s']<=20 and not TECH.search(r['baseline_raw'])),
         ('short',3,lambda r:0.5<=r['duration_s']<=3)]
 # Spread selected technical forms over history, avoid taking only newest same topic.
 for category,limit,predicate in groups:
  candidates=[r for r in rows if predicate(r) and r['audio_sha256'] not in seen]
  if not candidates:continue
  positions=sorted(set(round(i*(len(candidates)-1)/max(1,limit-1)) for i in range(min(limit,len(candidates)))))
  added=0
  for index in positions:
   if add(candidates[index],category):added+=1
  if added<limit:
   for r in candidates:
    if added>=limit:break
    if add(r,category):added+=1
 if len(selected)>16:raise ValueError('Scope exceeded')
 return selected


if __name__=='__main__':
 import argparse,os,random,struct
 p=argparse.ArgumentParser();p.add_argument('corpus');p.add_argument('destination');a=p.parse_args()
 root=Path(a.destination);root.mkdir(mode=0o700,exist_ok=False);audio_root=root/'audio';audio_root.mkdir(mode=0o700)
 rows=choose(a.corpus);records=[]
 for i,r in enumerate(rows,1):
  audio=r.pop('audio');f=audio_root/f'{i:02d}.wav';f.write_bytes(audio);f.chmod(0o600);records.append({**r,'file':str(f.relative_to(root))})
 for name,frames in [('silence',b'\0\0'*16000),('low_noise',b''.join(struct.pack('<h',random.Random(i+20261004).randint(-35,35)) for i in range(16000)))]:
  buf=io.BytesIO()
  with wave.open(buf,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(frames)
  audio=buf.getvalue();f=audio_root/(name+'.wav');f.write_bytes(audio);f.chmod(0o600)
  records.append({'sample_id':'synthetic-'+name,'audio_sha256':hashlib.sha256(audio).hexdigest(),'duration_s':1,'baseline_raw':None,'baseline_backend':None,'category':'negative_control','file':str(f.relative_to(root))})
 manifest={'records':records,'real_clips':len(rows),'real_audio_seconds':sum(r['duration_s'] for r in rows),'gold_reference':False,'hints':[],
  'candidate_models':['coriollon-whisper-codeswitch','gigaam-multilingual-large-ctc']}
 f=root/'manifest.json';f.write_text(json.dumps(manifest,ensure_ascii=False,indent=2));f.chmod(0o600)
 sha=hashlib.sha256(f.read_bytes()).hexdigest();(root/'manifest.sha256').write_text(sha+'\n');(root/'manifest.sha256').chmod(0o600)
 print(json.dumps({'real_clips':len(rows),'seconds':round(manifest['real_audio_seconds'],3),'controls':2,'categories':dict(Counter(r['category'] for r in records)),'manifest_sha256':sha}))
