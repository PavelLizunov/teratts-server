"""Finite actual Tailnet endpoint acceptance; all full responses stay private."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import urllib.request
import uuid


def transcribe(opener, url, raw, fields):
    boundary=uuid.uuid4().hex
    parts=[]
    from urllib.parse import urlencode
    query = {name: value for name, value in fields.items() if name in {'mode', 'format', 'dictionary', 'smart', 'cleanup'}}
    url = url + ('?' + urlencode(query) if query else '')
    for name,value in fields.items():
        if name in query:
            continue
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="test.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()+raw+b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    req=urllib.request.Request(url,data=b''.join(parts),headers={'Content-Type':f'multipart/form-data; boundary={boundary}'})
    start=time.perf_counter()
    with opener.open(req,timeout=120) as response:
        data=json.load(response);headers=dict(response.headers)
    return {'response':data,'headers':headers,'wall_s':time.perf_counter()-start,'audio_sha256':hashlib.sha256(raw).hexdigest(),'fields':fields}


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--phase',choices=['baseline','after'],required=True)
    p.add_argument('--url',default='https://steamdeck.tail9fd337.ts.net/v1/audio/transcriptions');args=p.parse_args()
    out=args.root/(args.phase+'-endpoint-query-private.json')
    if out.exists():raise RuntimeError('Immutable result exists')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));rows=[]
    for i in range(3):
        for name in ['1.wav','2.wav']:
            row=transcribe(opener,args.url,(args.root/'audio'/name).read_bytes(),{'mode':'default'})
            row['file']=name;rows.append(row)
            print(json.dumps({'file':name,'wall_s':row['wall_s'],'stt_ms':row['headers'].get('X-Stt-Latency-Ms'),
                              'sage_ms':row['headers'].get('X-Sage-Latency-Ms'),'formatting':row['headers'].get('X-Formatting-Status')}),flush=True)
    if args.phase=='after':
        for fields in [{'mode':'raw','dictionary':'false'},{'format':'false','dictionary':'false'},{'mode':'default','dictionary':'false'}]:
            row=transcribe(opener,args.url,(args.root/'audio/1.wav').read_bytes(),fields);row['file']='1.wav';rows.append(row)
    out.write_text(json.dumps(rows,ensure_ascii=False,indent=2));out.chmod(0o600)

if __name__=='__main__':main()
