"""Freeze five retained private WAVs and two synthetic controls before inference."""
import array
import base64
import hashlib
import io
import json
from pathlib import Path
import random
import re
import shlex
import subprocess
import wave

REMOTE = r'''
import base64,io,json,pathlib,tarfile,wave,re
root=pathlib.Path('/home/deck/homelab/voice-corpus')
ids=json.loads(input()); chosen=[]; seen=set()
def load(p):
 with tarfile.open(p) as t:
  d=json.load(t.extractfile('sample.json'))
  if d.get('kind')!='stt' or d.get('backend')!='parakeet' or 'original.wav' not in t.getnames():return
  b=t.extractfile('original.wav').read()
 with wave.open(io.BytesIO(b)) as w:
  if (w.getnchannels(),w.getsampwidth(),w.getframerate())!=(1,2,16000):return
  dur=w.getnframes()/16000
 return d,b,dur
for sid in ids:
 p=root/(sid+'.tar'); v=load(p)
 if v is None:raise RuntimeError('missing complaint')
 chosen.append((p,'complaint',v));seen.add(p.stem)
long=[];technical=[]
for p in sorted(root.glob('*.tar'),reverse=True)[:1800]:
 if p.stem in seen:continue
 v=load(p)
 if v is None:continue
 d,b,dur=v; text=d.get('raw_text','')
 if 18<=dur<=35 and len(long)<2:
  long.append((p,'long_natural',v));seen.add(p.stem)
 elif 7<=dur<=15 and re.search(r'github|omarchy|linux|[оау]марч|гитх|плаг|репозит',text,re.I) and not technical:
  technical.append((p,'technical',v));seen.add(p.stem)
 if len(long)==2 and technical:break
if len(long)!=2 or not technical:raise RuntimeError('selection incomplete')
chosen+=long+technical
if sum(v[2] for _,_,v in chosen)>120:raise RuntimeError('duration budget')
for p,category,(d,b,dur) in chosen:
 print(json.dumps({'id':p.stem,'category':category,'seconds':dur,'metadata':d,'wav_b64':base64.b64encode(b).decode()}))
'''


def control_bytes(noise=False):
    if noise:
        rng = random.Random(42)
        pcm = array.array('h', [rng.randint(-32, 32) for _ in range(16000)])
    else:
        pcm = array.array('h', [0] * 16000)
    out = io.BytesIO()
    with wave.open(out, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm.tobytes())
    return out.getvalue()


def prepare(root, complaint_ids):
    if len(complaint_ids) != 2 or any(not re.fullmatch(r'[0-9]{20}-[a-f0-9]{32}', sid) for sid in complaint_ids):
        raise ValueError('Require two exact private corpus IDs')
    root = Path(root)
    manifest = root / 'manifest.json'
    if manifest.exists():
        raise FileExistsError('Refuse to replace frozen manifest')
    clips = root / 'clips'
    clips.mkdir(mode=0o700, parents=True, exist_ok=True)
    proc = subprocess.run(
        ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', 'steamdeck',
         'python3 -c ' + shlex.quote(REMOTE)],
        input=json.dumps(complaint_ids), text=True, capture_output=True, timeout=120,
        check=True,
    )
    records = []
    for index, line in enumerate(proc.stdout.splitlines(), 1):
        row = json.loads(line)
        data = base64.b64decode(row.pop('wav_b64'), validate=True)
        path = clips / f'{index:02}.wav'
        path.write_bytes(data)
        path.chmod(0o600)
        row.update(path=str(path), sha256=hashlib.sha256(data).hexdigest(),
                   synthetic=False, human_reference=None)
        records.append(row)
    if len(records) != 5 or sum(r['seconds'] for r in records) > 120:
        raise ValueError('invalid selection')
    for name, noise in [('silence', False), ('low_noise', True)]:
        data = control_bytes(noise)
        path = clips / (name + '.wav')
        path.write_bytes(data)
        path.chmod(0o600)
        records.append(dict(id=name, category='control', seconds=1, path=str(path),
                            sha256=hashlib.sha256(data).hexdigest(), synthetic=True,
                            human_reference=''))
    value = dict(records=records, speech_seconds=sum(r['seconds'] for r in records if not r['synthetic']),
                 selection='two fixed complaint IDs; latest eligible two 18–35s and one technical 7–15s',
                 candidate_hints=False, candidates_started=False)
    manifest.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    manifest.chmod(0o600)
    print(json.dumps(dict(manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                          clips=len(records), speech_seconds=value['speech_seconds'])))


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('root')
    p.add_argument('--complaint-id', action='append', required=True)
    args = p.parse_args()
    prepare(args.root, args.complaint_id)
