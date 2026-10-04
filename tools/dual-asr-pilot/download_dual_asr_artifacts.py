"""Download pinned trial artifacts via configured reviewed proxy; no credentials."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def download(manifest,destination):
 destination=Path(destination);destination.mkdir(mode=0o700,exist_ok=True)
 rows=json.loads(Path(manifest).read_text());receipt=[]
 for r in rows:
  rel=Path(r['path'])
  if rel.is_absolute() or '..' in rel.parts:raise ValueError('Unsafe path')
  target=destination/r['model']/rel;target.parent.mkdir(parents=True,exist_ok=True)
  if not target.exists():
   partial=target.with_suffix(target.suffix+'.part')
   url='https://huggingface.co/'+r['repo']+'/resolve/'+r['revision']+'/'+r['path']
   subprocess.run(['curl','--fail','--location','--proto','=https','--proxy','http://192.168.0.142:18080',
     '--connect-timeout','8','--max-time','600','--output',str(partial),url],check=True)
   partial.rename(target)
  size=target.stat().st_size
  if size!=r['bytes']:raise ValueError('Wrong artifact size')
  with target.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
  if r['sha256']:
   if sha!=r['sha256']:raise ValueError('LFS SHA differs')
  else:
   if size>8*1024*1024:raise ValueError('Unexpected oversized Git blob')
   raw=target.read_bytes()
   git=hashlib.sha1(b'blob '+str(size).encode()+b'\0'+raw).hexdigest()
   if git!=r['blob_id']:raise ValueError('Git blob differs')
  receipt.append({**r,'local':str(target),'download_sha256':sha});print('VERIFIED '+r['model']+'/'+r['path'],flush=True)
 (destination/'verified-artifacts.json').write_text(json.dumps(receipt,indent=2))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('manifest');p.add_argument('destination');a=p.parse_args();download(a.manifest,a.destination)
