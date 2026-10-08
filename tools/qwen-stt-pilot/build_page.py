"""Generate private listening HTML from verified real receipts; never commit payload."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from run import validate_record

MODELS=[('parakeet','Parakeet v3','Q8_0 · Steam Deck Vulkan'),('qwen17','Qwen3-ASR 1.7B','BF16 · native CPU'),('qwen06','Qwen3-ASR 0.6B','BF16 · native CPU'),('nemotron','Nemotron 3.5 ASR','Q8_0 · NeMo CPU · русский'),('gigaam-ctc','GigaAM v3 CTC','Q8_0 · greedy CTC'),('gigaam-rnnt','GigaAM v3 RNNT','Q8_0 · RNNT'),('whisper-turbo','Whisper v3 turbo','Q8_0 · whisper.cpp CPU'),('whisper-large','Whisper large-v3','F16 · whisper.cpp CPU'),('whisper-russian','Whisper Russian','antony66 · native conversion'),('voxtral','Voxtral Realtime 4B','Q8_0 · native CPU'),('canary','Canary 1B v2','Q8_0 · native CPU'),('tone','T-one','ONNX · 8 кГц · greedy без LM'),('omni','OmniASR CTC 300M v2','HF conversion · float32 CPU')]


def short_error(error):
    if not error:return None
    if 'UnicodeDecodeError' in error:return 'Движок выдал повреждённый UTF-8. Это ошибка реализации, не оценка качества модели.'
    if 'time_budget' in error:return 'Превышен ограниченный бюджет времени.'
    if 'memory_budget' in error:return 'Превышен лимит памяти теста.'
    return error[:220]


def build(base,matrix,out):
    base,matrix,out=map(Path,(base,matrix,out));manifest_path=base/'manifest.json';m=json.loads(manifest_path.read_text());sha=hashlib.sha256(manifest_path.read_bytes()).hexdigest();b=json.loads((base/'parakeet-results.json').read_text())
    if b['exit_code'] or b['manifest_sha256']!=sha:raise ValueError('invalid baseline')
    baseline={r['id']:r for r in b['records']};models=[]
    for ident,name,detail in MODELS:
        if ident in ['parakeet','qwen17']:status='complete';error=None
        else:
            result_ident={'whisper-turbo':'whispercpp-turbo','whisper-large':'whispercpp-large'}.get(ident,ident)
            p=matrix/'results'/result_ident/'summary.json';s=json.loads(p.read_text()) if p.exists() else {};status=s.get('status','pending');error=s.get('error')
            presentation=matrix/'results'/result_ident/'presentation-status.json'
            if presentation.exists():
                overlay=json.loads(presentation.read_text());status=overlay.get('status',status);error=overlay.get('error',error)
            if status=='complete' and s.get('completed')!=7:raise ValueError('false complete '+ident)
        models.append(dict(id=ident,name=name,detail=detail,status=status,error=short_error(error)))
    clips=[]
    titles={'complaint':'Качество распознавания','long_natural':'Разговорная речь','technical':'Техническая фраза','control':'Контроль без речи'}
    for i,row in enumerate(m['records'],1):
        p=validate_record(row);results={}
        for model in models:
            ident=model['id'];res=None
            if ident=='parakeet':res=baseline[row['id']];actual=res['sha256']
            elif ident=='qwen17':res=json.loads((base/'qwen-results'/(row['id']+'.json')).read_text());actual=res['sha256']
            else:
                result_ident={'whisper-turbo':'whispercpp-turbo','whisper-large':'whispercpp-large'}.get(ident,ident)
                rp=matrix/'results'/result_ident/(row['id']+'.json')
                if rp.exists():res=json.loads(rp.read_text());actual=res['audio_sha256']
            if res:
                presentation=matrix/'results'/({'whisper-turbo':'whispercpp-turbo','whisper-large':'whispercpp-large'}.get(ident,ident))/'presentation-status.json'
                if presentation.exists() and json.loads(presentation.read_text()).get('invalid_results'):
                    res=dict(res,status='failed',text=None,error=model['error'])
                if actual!=row['sha256']:raise ValueError('wrong audio '+ident)
                if res.get('manifest_sha256',sha)!=sha:raise ValueError('wrong manifest '+ident)
                results[ident]=dict(status=res['status'],text=res.get('text'),error=short_error(res.get('error')),elapsed_s=res.get('elapsed_s'))
            else:results[ident]=dict(status='failed' if model['status']=='failed' else 'pending',text=None,error=short_error(model['error']),elapsed_s=None)
        title='Тишина' if row['id']=='silence' else 'Слабый шум' if row['id']=='low_noise' else titles[row['category']]
        clips.append(dict(id=row['id'],title=title,seconds=row['seconds'],synthetic=row['synthetic'],audio='data:audio/wav;base64,'+base64.b64encode(p.read_bytes()).decode(),results=results,audio_sha256=row['sha256']))
    payload=dict(manifest_sha256=sha,speech_seconds=m['speech_seconds'],generated=datetime.now(timezone.utc).isoformat(timespec='seconds'),models=models,clips=clips)
    template=Path(__file__).with_name('page.html').read_text();encoded=json.dumps(payload,ensure_ascii=False).replace('<','\\u003c');html=template.replace('__DATA__',encoded)
    if template.count('__DATA__')!=1:raise ValueError('template payload boundary')
    out.parent.mkdir(parents=True,exist_ok=True);temp=out.with_suffix('.part');temp.write_text(html);temp.chmod(0o600);temp.replace(out)
    print(json.dumps(dict(path=str(out),bytes=out.stat().st_size,models=len(models),complete=sum(x['status']=='complete' for x in models),pending=[x['id'] for x in models if x['status']=='pending']),ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('base');p.add_argument('matrix');p.add_argument('output');a=p.parse_args();build(a.base,a.matrix,a.output)
