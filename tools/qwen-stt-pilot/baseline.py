"""Replay fixed WAVs directly to retained Parakeet without corpus-ingest side effects."""
import base64
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
from run import atomic_json, validate_record

REMOTE = r'''
import base64,hashlib,json,time,urllib.request
rows=json.load(__import__('sys').stdin)
for row in rows:
 audio=base64.b64decode(row['wav_b64'],validate=True)
 if hashlib.sha256(audio).hexdigest()!=row['sha256']:raise ValueError('transfer hash')
 boundary='BoundedQwenBaselineReplay'
 body=(f'--{boundary}\r\nContent-Disposition: form-data; name="response_format"\r\n\r\njson\r\n'
       f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
       'Content-Type: audio/wav\r\n\r\n').encode()+audio+f'\r\n--{boundary}--\r\n'.encode()
 req=urllib.request.Request('http://127.0.0.1:10001/v1/audio/transcriptions',data=body,
  headers={'Content-Type':f'multipart/form-data; boundary={boundary}'})
 started=time.monotonic()
 try:
  with urllib.request.urlopen(req,timeout=60) as r: result=json.load(r)
  out=dict(id=row['id'],sha256=row['sha256'],synthetic=row['synthetic'],status='success',text=result.get('text',''),elapsed_s=time.monotonic()-started)
 except Exception as e:out=dict(id=row['id'],status='failed',error=type(e).__name__+': '+str(e))
 print(json.dumps(out,ensure_ascii=False),flush=True)
 if out['status']!='success':raise RuntimeError('baseline failed')
'''


def baseline(root):
    root = Path(root)
    output = root / 'parakeet-results.json'
    if output.exists():
        raise FileExistsError('Refuse duplicate replay')
    manifest_path = root / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    rows = []
    for row in manifest['records']:
        path = validate_record(row)
        rows.append(dict(id=row['id'], sha256=row['sha256'], synthetic=row['synthetic'],
                         wav_b64=base64.b64encode(path.read_bytes()).decode()))
    proc = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                           'steamdeck', 'python3 -c ' + shlex.quote(REMOTE)],
                          input=json.dumps(rows), text=True, capture_output=True, timeout=180)
    (root / 'parakeet-replay-stdout.txt').write_text(proc.stdout)
    (root / 'parakeet-replay-stderr.txt').write_text(proc.stderr)
    parsed = [json.loads(line) for line in proc.stdout.splitlines()]
    receipt = dict(exit_code=proc.returncode, records=parsed,
                   manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                   model='nvidia/parakeet-tdt-0.6b-v3',
                   revision='541d1f99c6b0c3cd0b11a95167540bb8edefd82b',
                   precision='Q8_0', engine='nemo-speech 0.1.0 Vulkan', host='steamdeck')
    atomic_json(output, receipt)
    if proc.returncode or len(parsed) != 7 or any(r['status'] != 'success' for r in parsed):
        raise RuntimeError('Incomplete baseline: inspect persisted terminal output')
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('root')
    baseline(p.parse_args().root)
