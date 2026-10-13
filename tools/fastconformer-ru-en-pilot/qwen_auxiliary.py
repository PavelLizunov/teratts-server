"""Pinned Qwen whole-audio auxiliary proposals; never final constrained ASR."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import wave

from mms_pair import digest,save
from pilot import rss_bytes
from run import memory_snapshot


def execute(manifest_path):
    cfg=json.loads(Path(manifest_path).read_text());out=Path(cfg['output']);out.mkdir(mode=0o700,exist_ok=False)
    for name,sha in cfg['source_files'].items():
        if digest(Path(__file__).parent/name)!=sha:raise ValueError('Changed frozen source')
    for filename,sha in cfg['runtime_assets'].items():
        if digest(filename)!=sha:raise ValueError('Changed runtime asset: '+filename)
    root=Path(cfg['model']);receipt=json.loads((root/'fetch-receipt.json').read_text())
    if receipt['revision']!=cfg['model_revision']:raise ValueError('Changed model revision')
    for row in receipt['files']:
        f=root/row['path']
        if f.stat().st_size!=row['bytes'] or digest(f)!=row['sha256']:raise ValueError('Changed pinned model file')
    begin=time.monotonic();rows=[]
    env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','LANG')}
    env.update(OPENBLAS_NUM_THREADS='2',OMP_NUM_THREADS='2',CUDA_VISIBLE_DEVICES='',LD_LIBRARY_PATH=cfg['library_path'])
    for item in cfg['recordings']:
        if time.monotonic()-begin>900:raise TimeoutError('Auxiliary batch deadline; preserve completed cells')
        path=Path(item['wav']);expected=item['sha256'];stem=out/item['id']
        if digest(path)!=expected:raise ValueError('Original WAV changed')
        with wave.open(str(path),'rb') as wav:
            geometry=(wav.getnchannels(),wav.getsampwidth(),wav.getframerate(),wav.getcomptype())
            if geometry!=(1,2,16000,'NONE'):raise ValueError('Original WAV geometry mismatch')
            samples=wav.getnframes()
        if samples/16000!=item['duration_s']:raise ValueError('Original duration changed')
        base=memory_snapshot()
        if base['MemAvailable']<(4096+2048)*1048576:raise RuntimeError('Insufficient available memory before Qwen load')
        if item.get('reuse'):
            reuse=item['reuse']
            if digest(reuse['path'])!=reuse['sha256']:raise ValueError('Retained auxiliary changed')
            old=json.loads(Path(reuse['path']).read_text())
            result={'id':item['id'],'status':'success','hypotheses':[{'raw_text':old['text']}],
                    'audio_sha256':expected,'new_model_call':False,'reused_receipt':reuse,'elapsed_s':0.}
            save(stem.with_suffix('.json'),result);rows.append(result);continue
        command=[cfg['binary'],'-d',cfg['model'],'-i',str(path),'-t','2','-S','0','--past-text','no','--silent']
        save(out/(item['id']+'-started.json'),{'audio_sha256':expected,'manifest_sha256':digest(manifest_path),'command':command,'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})
        started=time.monotonic();measure=[];reason=None
        with stem.with_suffix('.stdout').open('xb') as stdout,stem.with_suffix('.stderr').open('xb') as stderr:
            p=subprocess.Popen(['nice','-n','19',*command],env=env,stdout=stdout,stderr=stderr,start_new_session=True)
            try:
                while p.poll() is None:
                    m=memory_snapshot();rss=rss_bytes(p.pid);elapsed=time.monotonic()-started
                    measure.append({'elapsed_s':elapsed,'rss_mib':rss/1048576,'available_mib':m['MemAvailable']/1048576,'swap_growth_mib':max(0,m['swap_used']-base['swap_used'])/1048576})
                    if rss>4096*1048576 or m['MemAvailable']<2048*1048576 or m['swap_used']-base['swap_used']>256*1048576:reason='resource_guard';break
                    if elapsed>180 or time.monotonic()-begin>900:reason='time_guard';break
                    time.sleep(.1)
            finally:
                if p.poll() is None:
                    os.killpg(p.pid,signal.SIGTERM)
                    try:p.wait(timeout=10)
                    except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
        raw=stem.with_suffix('.stdout').read_text();error=reason or ('native_exit_'+str(p.returncode) if p.returncode else None)
        if digest(path)!=expected:error='Original WAV changed during run'
        text=raw.strip()
        result={'id':item['id'],'status':'failed' if error else 'success','error':error,'exit_code':p.returncode,
                'audio_sha256':expected,'whole_audio_samples':samples,'new_model_call':True,'elapsed_s':time.monotonic()-started,
                'hypotheses':[{'raw_text':text}] if not error else [],'stdout_sha256':digest(stem.with_suffix('.stdout')),
                'stderr_sha256':digest(stem.with_suffix('.stderr')),'command':command,'samples':measure,
                'model_revision':cfg['model_revision'],'engine_revision':cfg['engine_revision'],
                'model_tensor_parameters':cfg['model_tensor_parameters'],'source_commit':cfg['source_commit'],
                'manifest_sha256':digest(manifest_path),'proposal_only_not_final_output':True,
                'strict_language_pair':False,'language':'auto','hints':False,'past_text':False,'segmentation':False,
                'appended_audio_padding':False,'native_frontend':'centered STFT reflect handling, original entire waveform',
                'local_host_not_deck':True}
        save(stem.with_suffix('.json'),result);rows.append({k:result[k] for k in ('id','status','error','elapsed_s','new_model_call')})
        print(item['id'],result['status'],round(result['elapsed_s'],3),flush=True)
        if reason:
            save(out/'summary.json',{'status':'stopped','reason':reason,'rows':rows,'elapsed_s':time.monotonic()-begin});raise RuntimeError(reason)
    save(out/'summary.json',{'status':'completed','rows':rows,'elapsed_s':time.monotonic()-begin,'new_model_calls':sum(r['new_model_call'] for r in rows)})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('manifest');a=p.parse_args();execute(a.manifest)
