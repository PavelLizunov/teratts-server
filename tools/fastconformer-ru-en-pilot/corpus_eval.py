"""Frozen collected-speech sample and sequential isolated full-pipeline evaluation."""
import argparse
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import time
import wave

from mms_pair import digest,save
from run import memory_snapshot

DEVELOPMENT={'f8b7da4ac0335095e9e8542bf25e1f4191d930fa8b2fb662bcb1840fdb1e8d7a','8d9314f71c42f554d0a26f5e7da9fb5ea72f1e451272e1c5bb014a019bc5ea50'}
TECH=re.compile(r'чат.?гп|чат.?дж|ди.?эс.?эйч|оракл|оракул|стим.?д[еэ]|омарч|умарч|гитх|линукс|бонса|банса|квен|квэн|пар[аэ]кет|д[иэ]псик',re.I)


def select(args):
    source=json.loads(Path(args.inventory).read_text());bins={'latin':[],'technical_proxy':[],'other_russian':[]};exclude=Counter();seen=set()
    for row in source['stt_records']:
        reason=None
        if row['audio_sha256'] in DEVELOPMENT:reason='development_audio'
        elif row['synthetic_request']:reason='synthetic_request'
        elif row['audio_origin']!='submitted_stt_request' or not row['has_original_wav']:reason='not_original_human_stt'
        elif (row.get('dictionary') or {}).get('status')=='request_disabled':reason='dictionary_optout'
        elif (row['channels'],row['sample_width'],row['sample_rate'])!=(1,2,16000):reason='unsupported_format'
        elif not 2<=row['audio_duration_s']<=30:reason='outside_2_30_seconds'
        elif row['audio_sha256'] in seen:reason='duplicate_audio'
        elif not (row.get('raw_text') or '').strip():reason='empty_saved_primary'
        if reason:exclude[reason]+=1;continue
        seen.add(row['audio_sha256']);text=row['raw_text']
        category='latin' if re.search('[a-zA-Z]',text) else 'technical_proxy' if TECH.search(text) else 'other_russian'
        bins[category].append(row)
    selected=[]
    for category,rows in bins.items():
        n=min(10,len(rows));indices=sorted({round(i*(len(rows)-1)/(n-1)) if n>1 else 0 for i in range(n)})
        for i in indices:selected.append(dict(rows[i],stratum=category))
    selected.sort(key=lambda r:r['sample_id'])
    for i,r in enumerate(selected,1):r['id']=f'c{i:03}'
    result={'inventory_sha256':digest(args.inventory),'selection':'10 chronology-spread per saved-text stratum; no model-output selection','reference_policy':'saved model output, not human gold',
            'eligible_by_stratum':{k:len(v) for k,v in bins.items()},'exclusions':dict(exclude),'selected':len(selected),'duration_s':sum(r['audio_duration_s'] for r in selected),'records':selected}
    save(Path(args.output),result)
    print(json.dumps({k:v for k,v in result.items() if k!='records'},ensure_ascii=False,indent=2))


def prepare(args):
    selection=json.loads(Path(args.selection).read_text());root=Path(args.root);root.mkdir(mode=0o700,exist_ok=False);clips=root/'clips';clips.mkdir(mode=0o700)
    records=[];errors=[]
    for row in selection['records']:
        try:
            with tarfile.open(Path(args.corpus)/row['filename']) as archive:
                m=json.load(archive.extractfile('sample.json'));data=archive.extractfile('original.wav').read()
            if hashlib.sha256(data).hexdigest()!=row['audio_sha256'] or m['audio_sha256']!=row['audio_sha256']:raise ValueError('Changed original audio')
            if (m.get('dictionary') or {}).get('status')=='request_disabled':raise ValueError('Current opt-out')
            with wave.open(io.BytesIO(data)) as f:
                if (f.getnchannels(),f.getsampwidth(),f.getframerate(),f.getcomptype())!=(1,2,16000,'NONE'):raise ValueError('Wrong original WAV format')
                duration=f.getnframes()/16000;pcm=f.readframes(f.getnframes())
                if not pcm.strip(b'\0'):raise ValueError('Zero PCM silence')
                if abs(duration-row['audio_duration_s'])>.001:raise ValueError('Duration changed')
            path=clips/(row['id']+'.wav')
            with path.open('xb') as file:file.write(data)
            path.chmod(0o600);save(clips/(row['id']+'-metadata.json'),m)
            records.append({'id':row['id'],'wav':str(path),'sha256':row['audio_sha256'],'duration_s':duration,'sample_id':row['sample_id'],'stratum':row['stratum']})
        except (OSError,ValueError,KeyError,tarfile.TarError,wave.Error) as e:errors.append({'id':row['id'],'error':type(e).__name__+': '+str(e)})
    save(root/'prepared-corpus.json',{'selection_sha256':digest(args.selection),'recordings':records,'preparation_errors':errors})
    print(json.dumps({'prepared':len(records),'errors':errors},ensure_ascii=False,indent=2))


def run(args):
    cfg=json.loads(Path(args.manifest).read_text());output=Path(cfg['results_directory']);output.mkdir(mode=0o700,exist_ok=False)
    records=cfg['recordings'];statuses=[];start=time.monotonic()
    for clip in records:
        available=memory_snapshot()['MemAvailable']/1048576
        waiting=[];deadline=time.monotonic()+cfg.get('capacity_wait_seconds',0)
        while available<2048+cfg['rss_mib'] and time.monotonic()<deadline:
            waiting.append({'time_unix':time.time(),'available_mib':available})
            time.sleep(2);available=memory_snapshot()['MemAvailable']/1048576
        if waiting:save(output/(clip['id']+'-capacity-wait.json'),waiting)
        if available<2048+cfg['rss_mib']:
            save(output/(clip['id']+'-not-started.json'),{'reason':'insufficient_preflight_budget','available_mib':available,'required_mib':2048+cfg['rss_mib']})
            print('budget pause before',clip['id'],available,flush=True);break
        one=dict(cfg,recordings=[clip],results_directory=str(output/clip['id']));path=output/(clip['id']+'-manifest.json');save(path,one)
        save(output/(clip['id']+'-started.json'),{'time_unix':time.time(),'manifest_sha256':digest(path)})
        command=[sys.executable,str(Path(__file__).with_name('paired_pipeline.py')),'pilot',str(path)]
        with (output/(clip['id']+'.stdout')).open('xb') as out,(output/(clip['id']+'.stderr')).open('xb') as err:
            code=subprocess.run(command,stdout=out,stderr=err).returncode
        receipt=output/clip['id']/(clip['id']+'-pipeline.json')
        value=json.loads(receipt.read_text()) if receipt.exists() else {'status':'unknown','stages':[]}
        row={'id':clip['id'],'exit_code':code,'status':value['status'],'elapsed_s':value.get('elapsed_s'),'stop_reason':next((s['stop_reason'] for s in value['stages'] if s.get('stop_reason')),None)}
        statuses.append(row);save(output/(clip['id']+'-settled.json'),row);print(json.dumps(row),flush=True)
        if row['stop_reason'] or row['status']=='unknown':break
    save(output/'evaluation-summary.json',{'manifest_sha256':digest(args.manifest),'elapsed_s':time.monotonic()-start,'selected':len(records),'settled':statuses,'untouched_ids':[r['id'] for r in records[len(statuses):]],'no_automatic_retries':True})


if __name__=='__main__':
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='mode',required=True)
    q=s.add_parser('select');q.add_argument('inventory');q.add_argument('output')
    q=s.add_parser('prepare');q.add_argument('selection');q.add_argument('corpus');q.add_argument('root')
    q=s.add_parser('run');q.add_argument('manifest');a=p.parse_args();globals()[a.mode](a)
