"""Resumable sequential resident no-hint ASR corpus pass, loopback only.

Progress/results private and atomic. Started-only markers become interrupted
(unresolved) without blind retry. Production STT activity yields before dispatch.
"""
import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request
import wave

from nemotron_corpus_snapshot import atomic_json,wav_info

MODEL_SHA='3fc991d3badad7277c11030a7519832cddaf2057aafed6d4b25147e953a070b1'
MODEL_REV='ea30d66debe3740a08b573244286791d423d6b3e'


def validate_manifest(root):
    raw=(root/'manifest.json').read_bytes()
    digest=hashlib.sha256(raw).hexdigest()
    if digest!=(root/'manifest.sha256').read_text().strip():raise ValueError('Manifest changed')
    data=json.loads(raw);seen=set()
    for row in data['records']:
        sha=row['audio_sha256']
        if len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha) or sha in seen:raise ValueError('Invalid audio identity')
        if row['file']!='audio/'+sha+'.wav':raise ValueError('Invalid frozen path')
        seen.add(sha)
    if len(seen)!=data['unique_audio']:raise ValueError('Incomplete manifest')
    return data,digest


def idle_reason(corpus):
    available=0
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):available=int(line.split()[1])*1024
    if available<2*1024**3:return 'low_available_memory'
    try:
        activity=subprocess.run(['ss','-Htn','state','established','( sport = :10000 or sport = :10001 )'],
                                capture_output=True,text=True,timeout=2)
        if activity.returncode==0 and activity.stdout.strip():return 'production_stt_connection'
        paths=list(corpus.glob('*.tar'))
        # Native transcription corpus record timestamps indicate recent demand,
        # though idle detection cannot guarantee absence of a future request.
        if paths and time.time()-max(p.stat().st_mtime for p in paths)<5:return 'recent_corpus_activity'
    except (OSError,subprocess.TimeoutExpired):return 'activity_probe_unavailable'
    return None


def transcribe(opener,url,audio,timeout):
    boundary='nemotron-'+hashlib.sha256(audio).hexdigest()[:16]
    parts=[]
    for name,value in [('language','ru'),('response_format','verbose_json'),('automatic_punctuation','true'),('verbatim','false')]:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="recording.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()+audio+b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    request=urllib.request.Request(url+'/v1/audio/transcriptions',data=b''.join(parts),
        headers={'Content-Type':f'multipart/form-data; boundary={boundary}'})
    with opener.open(request,timeout=timeout) as response:
        raw=response.read(8*1024*1024+1)
        if len(raw)>8*1024*1024:raise ValueError('Oversized response')
        data=json.loads(raw)
        if not isinstance(data.get('text'),str):raise ValueError('Invalid response text')
        return data


def progress(root,manifest,model,completed,pause=None,finished=False):
    counts=Counter(row['status'] for row in completed)
    durations=[row['elapsed_s'] for row in completed if row['status']=='completed']
    data={'updated_unix':time.time(),'total_unique_audio':manifest['unique_audio'],'resolved_results':len(completed),
          'statuses':dict(counts),'remaining':manifest['unique_audio']-len(completed),'paused_reason':pause,
          'finished':finished,'coverage_complete':len(completed)==manifest['unique_audio'],
          'model_sha256':model,'mode':'plain_no_hints','device':'cpu','gold_accuracy_measured':False,
          'successful_inference_seconds':round(sum(durations),3)}
    atomic_json(root/'progress.json',data)
    return data


def run(root,corpus,model,url):
    if url not in ['http://127.0.0.1:10004']:raise ValueError('Only isolated loopback endpoint permitted')
    data,manifest_sha=validate_manifest(root)
    with model.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=MODEL_SHA:raise ValueError('Model hash mismatch')
    evaluator_sha=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    contract={'model_sha256':MODEL_SHA,'model_revision':MODEL_REV,'manifest_sha256':manifest_sha,
              'evaluator_sha256':evaluator_sha,'endpoint':url,'mode':'plain_no_hints','device':'cpu','language':'ru',
              'gold_accuracy_measured':False,'production_switch':False}
    contract_path=root/'run-contract.json'
    if contract_path.exists() and json.loads(contract_path.read_text())!=contract:raise ValueError('Run contract differs')
    if not contract_path.exists():atomic_json(contract_path,contract)
    output=root/'results';output.mkdir(mode=0o700,exist_ok=True)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url+'/ready',timeout=5) as r:ready=json.load(r)
    if not ready.get('ready') or ready.get('device') not in [None,'cpu']:raise ValueError('Trial decoder not ready/CPU')
    # Exact silence control once per resident run identity, not user data.
    control=root/'silence-control.json'
    if not control.exists():
        buf=io.BytesIO()
        with wave.open(buf,'wb') as wav:wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(b'\0\0'*16000)
        answer=transcribe(opener,url,buf.getvalue(),30)
        atomic_json(control,{'text':answer['text'],'model_sha256':MODEL_SHA,'passed_empty':not answer['text'].strip()})
        if answer['text'].strip():raise ValueError('Silence hallucination guard')
    elif not json.loads(control.read_text()).get('passed_empty'):raise ValueError('Prior silence failed')
    results=[]
    for index,row in enumerate(data['records'],1):
        sha=row['audio_sha256'];path=output/(sha+'.json');started=output/(sha+'.started.json')
        if path.exists():
            prior=json.loads(path.read_text())
            if prior.get('audio_sha256')!=sha or prior.get('manifest_sha256')!=manifest_sha:raise ValueError('Invalid previous result')
            results.append(prior);continue
        if started.exists():
            result={**contract,'audio_sha256':sha,'status':'interrupted_unknown_no_retry','sources':row['sources'],
                    'duration_s':row['duration_s'],'elapsed_s':0}
            atomic_json(path,result);results.append(result);continue
        while True:
            reason=idle_reason(corpus)
            if reason is None:break
            progress(root,data,MODEL_SHA,results,reason)
            time.sleep(2)
        audio=(root/row['file']).read_bytes()
        if len(audio)!=row['audio_bytes'] or hashlib.sha256(audio).hexdigest()!=sha:raise ValueError('Frozen WAV changed')
        wav_info(audio)
        atomic_json(started,{'started_unix':time.time(),'audio_sha256':sha,'manifest_sha256':manifest_sha})
        now=time.monotonic();result={**contract,'audio_sha256':sha,'duration_s':row['duration_s'],
             'source_count':len(row['sources']),'sources':row['sources'],'status':'completed'}
        infrastructure=False
        try:
            answer=transcribe(opener,url,audio,max(90,min(900,row['duration_s']*5+30)))
            result.update(result=answer,elapsed_s=round(time.monotonic()-now,4))
        except urllib.error.HTTPError as error:
            result.update(status='http_failure',http_status=error.code,error_type=type(error).__name__,elapsed_s=round(time.monotonic()-now,4))
            infrastructure=error.code>=500
        except (OSError,ValueError,urllib.error.URLError) as error:
            result.update(status='inference_failed_or_unknown_no_retry',error_type=type(error).__name__,elapsed_s=round(time.monotonic()-now,4))
            infrastructure=True
        atomic_json(path,result);results.append(result)
        status=progress(root,data,MODEL_SHA,results)
        print(json.dumps({'index':index,'total':len(data['records']),'status':result['status'],
                          'seconds':result['elapsed_s'],'remaining':status['remaining']}),flush=True)
        if infrastructure:raise RuntimeError('Trial infrastructure failure; resumable results preserved')
    final=progress(root,data,MODEL_SHA,results,finished=True)
    print('FULL_PASS_FINISHED '+json.dumps(final),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--corpus',type=Path,required=True)
    p.add_argument('--model',type=Path,required=True);p.add_argument('--endpoint',default='http://127.0.0.1:10004')
    a=p.parse_args();run(a.root,a.corpus,a.model,a.endpoint)
