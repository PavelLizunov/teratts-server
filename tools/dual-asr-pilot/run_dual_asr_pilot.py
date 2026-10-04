"""Finite paired offline CPU ASR trial, transcript hypotheses not human gold."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import time
import wave


def atomic(path,data):
    temp=path.with_suffix(path.suffix+'.part')
    with temp.open('w') as out:
        json.dump(data,out,ensure_ascii=False,indent=2);out.flush();os.fsync(out.fileno())
    temp.chmod(0o600);temp.replace(path)


def validate(root,which=None):
    root=Path(root);manifest=root/'dual-asr-snapshot-20261004/manifest.json'
    digest=hashlib.sha256(manifest.read_bytes()).hexdigest()
    expected=(manifest.with_suffix('.sha256')).read_text().strip()
    if digest!=expected:raise ValueError('Manifest changed')
    m=json.loads(manifest.read_text());records=m['records']
    if len(records)!=18 or m['real_clips']!=16 or m['real_audio_seconds']>180:raise ValueError('Wrong bounded trial size')
    if len({r['audio_sha256'] for r in records})!=18:raise ValueError('Repeated source audio')
    if sum(r['category']=='negative_control' for r in records)!=2:raise ValueError('Missing controls')
    for row in records:
        rel=Path(row['file'])
        if rel.is_absolute() or '..' in rel.parts:raise ValueError('Unsafe audio path')
        wav=manifest.parent/rel
        if wav.is_symlink() or hashlib.sha256(wav.read_bytes()).hexdigest()!=row['audio_sha256']:raise ValueError('Changed audio')
        with wave.open(str(wav)) as w:
            if (w.getnchannels(),w.getsampwidth(),w.getframerate())!=(1,2,16000):raise ValueError('Unsupported audio')
    receipt=json.loads((root/'models/verified-artifacts.json').read_text())
    for item in receipt:
        if which is not None and item['model']!=which:continue
        file=root/'models'/item['model']/item['path']
        with file.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        if sha!=item['download_sha256'] or file.stat().st_size!=item['bytes']:raise ValueError('Model artifact changed')
    return m,digest


def run(root,which):
    root=Path(root);m,digest=validate(root,which);out=root/'results'/which;out.mkdir(mode=0o700,parents=True,exist_ok=True)
    if os.environ.get('CUDA_VISIBLE_DEVICES')!='':raise ValueError('Must hide GPU')
    import sys
    def prohibit_network(event,args):
        if event in {'socket.connect','socket.getaddrinfo','socket.bind'}:raise RuntimeError('Inference network forbidden')
    sys.addaudithook(prohibit_network)
    start=time.monotonic()
    if which=='whisper':
        from faster_whisper import WhisperModel
        model=WhisperModel(str(root/'models/whisper/ct2_int8_float16'),device='cpu',compute_type='int8',cpu_threads=2,num_workers=1,local_files_only=True)
        params={'language':'ru','task':'transcribe','beam_size':5,'temperature':0,'condition_on_previous_text':False,
                'vad_filter':False,'initial_prompt':None,'hotwords':None,'word_timestamps':False}
        def recognize(path):
            import numpy as np
            with wave.open(str(path)) as wav:
                pcm=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').astype(np.float32)/32768.0
            segments,info=model.transcribe(pcm,**params)
            segments=list(segments)
            return ' '.join(s.text.strip() for s in segments).strip(),{'language':info.language,'language_probability':info.language_probability,
                 'segments':[{'start':s.start,'end':s.end,'text':s.text,'no_speech_prob':s.no_speech_prob,'avg_logprob':s.avg_logprob} for s in segments]}
        revision='bf64d2a976a268e35041f74233f889f951f0f676'
    else:
        import torch
        import importlib.util
        import sys
        torch.set_num_threads(2);torch.set_num_interop_threads(1)
        source=root/'models/gigaam/modeling_gigaam.py'
        spec=importlib.util.spec_from_file_location('modeling_gigaam',source)
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
        config=module.GigaAMConfig.from_pretrained(str(root/'models/gigaam'),local_files_only=True)
        model=module.GigaAMModel.from_pretrained(str(root/'models/gigaam'),config=config,local_files_only=True,
                                        use_safetensors=False,dtype=torch.float32,weights_only=True).to('cpu').eval()
        params={'decoder':'CTC greedy','punctuation_model':None,'external_lm':None,'dtype':'float32','threads':2}
        def recognize(path):
            with torch.inference_mode():result=model.transcribe(str(path))
            return result.text,{'words':None}
        revision='3905cd51c3ed4e88c8edf33f3302969ba480a327'
    load_seconds=time.monotonic()-start
    atomic(out/'runtime.json',{'model':which,'revision':revision,'device':'cpu','load_seconds':load_seconds,'params':params,
                             'manifest_sha256':digest,'offline':True,'no_hints':True,'human_gold':False})
    def timeout(signum,frame):raise TimeoutError('Bounded audio call exceeded180sec')
    signal.signal(signal.SIGALRM,timeout)
    for i,row in enumerate(m['records'],1):
        path=out/f'{i:02d}.json';marker=out/f'{i:02d}.started'
        if path.exists():continue
        if marker.exists():raise RuntimeError('Prior dispatch ambiguous: no automatic duplication')
        marker.write_text(str(time.time()));marker.chmod(0o600)
        started=time.monotonic();signal.alarm(180)
        try:
            text,extra=recognize(root/'dual-asr-snapshot-20261004'/row['file'])
            data={'clip':i,'sample_id':row['sample_id'],'audio_sha256':row['audio_sha256'],'category':row['category'],
                  'duration_s':row['duration_s'],'comparison_model':which,'revision':revision,'text':text,'extra':extra,
                  'seconds':time.monotonic()-started,'manifest_sha256':digest,'success':True,'human_gold':False,'no_hints':True}
        except Exception as error:
            data={'clip':i,'audio_sha256':row['audio_sha256'],'success':False,'error_type':type(error).__name__,'error':str(error)}
        finally:signal.alarm(0)
        atomic(path,data)
        print(json.dumps({'model':which,'clip':i,'success':data['success'],'seconds':round(data.get('seconds',0),3),'text_characters':len(data.get('text',''))}),flush=True)
        if not data['success']:raise RuntimeError('Stopped trial after captured failure')
    atomic(out/'complete.json',{'model':which,'results':len(m['records']),'manifest_sha256':digest,'complete':True})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('model',choices=['whisper','gigaam']);a=p.parse_args();run(a.root,a.model)
