"""Guarded all-path word evidence on saved corpus CTC arrays; no ASR rerun."""
import argparse
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

from ctc_occurrence import enumerate_controls, occurrence
from english_timing import auxiliary_words, english_timing_labels
from mms_pair import HINTS, digest, save
from pilot import rss_bytes
from run import Guard, memory_snapshot


def worker(manifest_path):
    import numpy as np
    import sentencepiece as spm
    cfg=json.loads(Path(manifest_path).read_text());out=Path(cfg['output'])
    guard=Guard(600,1536);start=time.monotonic()
    controls=enumerate_controls();save(out/'enumeration-controls.json',{'rows':controls,'not_asr_accuracy':True})
    ep=Path(cfg['english_model']);prepared=json.loads((ep/'prepared.json').read_text())
    if digest(ep/'tokenizer.model')!=prepared['tokenizer_sha256']:raise ValueError('Changed tokenizer')
    sp=spm.SentencePieceProcessor(model_file=str(ep/'tokenizer.model'))
    pieces=[prepared['vocab'][str(i)] for i in range(1025)];pieces[0]=pieces[1024]=''
    normalize=lambda s:s.lower() if prepared['english_case']=='lower' else s
    collected=[]
    for item in cfg['recordings']:
        guard.check();begin=time.monotonic()
        for k in ('aux','eng'):
            if digest(item[k])!=item['hashes'][k]:raise ValueError('Changed saved input')
        aux=json.loads(Path(item['aux']).read_text());en=json.loads(Path(item['eng']).read_text())
        if aux['audio_sha256']!=en['audio_sha256']:raise ValueError('Mixed original audio')
        if digest(ep/'prepared.json')!=en['prepared_sha256']:raise ValueError('Changed trained mapping')
        array=Path(item['eng']).with_suffix('.npz')
        if digest(array)!=en['retained_array_sha256']:raise ValueError('Changed English array')
        with np.load(array) as f:lp=f['values'].astype(np.float64)
        lp[:,0]=-np.inf;lp-=np.logaddexp.reduce(lp,axis=1,keepdims=True)
        targets={normalize(s):{'sources':['fixed_hint'],'auxiliary_occurrences':0} for s in HINTS};unsupported=[]
        for word in auxiliary_words(aux['hypotheses'][0]['raw_text']):
            try:_,records=english_timing_labels(word,sp,prepared['english_case'])
            except ValueError:unsupported.append(word);continue
            if records[0]['role']=='english_timing':
                q=normalize(word);meta=targets.setdefault(q,{'sources':[],'auxiliary_occurrences':0})
                if 'auxiliary_word' not in meta['sources']:meta['sources'].append('auxiliary_word')
                meta['auxiliary_occurrences']+=1
        raw_greedy=[];previous=1024
        for value in lp.argmax(axis=1):
            value=int(value)
            if value!=previous and value!=1024:raw_greedy.append(value)
            previous=value
        greedy=normalize(' '.join(auxiliary_words(sp.decode(raw_greedy))))
        rows=[]
        for target,meta in sorted(targets.items()):
            before=time.monotonic();value=occurrence(lp,pieces,1024,target,guard.check)
            value.update(meta,elapsed_s=time.monotonic()-before,greedy_contains_whole_target=(' '+target+' ') in (' '+greedy+' '))
            rows.append(value)
        result={'id':item['id'],'audio_sha256':en['audio_sha256'],'targets':rows,'unsupported_auxiliary_words':unsupported,
                'greedy_english_text':greedy,'elapsed_s':time.monotonic()-begin,'source_commit':cfg['source_commit'],
                'english_receipt_sha256':item['hashes']['eng'],'array_sha256':en['retained_array_sha256'],
                'no_encoder_or_audio_pass':True,'no_transcript_output':True,'not_a_language_gate':True}
        save(out/(item['id']+'.json'),result);collected.append({'id':item['id'],'targets':len(rows),'elapsed_s':result['elapsed_s']})
        print(item['id'],'targets',len(rows),'seconds',round(result['elapsed_s'],3),flush=True)
    save(out/'summary.json',{'status':'success','rows':collected,'elapsed_s':time.monotonic()-start,
                            'peak_rss_mib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                            'guard':guard.receipt(),'enumeration_controls':len(controls),
                            'new_model_calls':0,'human_gold_records':0})


def pilot(manifest_path):
    cfg=json.loads(Path(manifest_path).read_text());out=Path(cfg['output']);out.mkdir(mode=0o700,exist_ok=False)
    for name,sha in cfg['source_files'].items():
        if digest(Path(__file__).parent/name)!=sha:raise ValueError('Changed frozen source')
    start=time.monotonic();base=memory_snapshot();samples=[];reason=None
    if base['MemAvailable']<(1536+2048)*1048576:raise RuntimeError('Insufficient budget before start')
    with (out/'worker.log').open('x') as log:
        p=subprocess.Popen([cfg['python'],str(Path(__file__).resolve()),'worker',str(manifest_path)],stdout=log,stderr=subprocess.STDOUT)
        try:
            while p.poll() is None:
                m=memory_snapshot();rss=rss_bytes(p.pid);elapsed=time.monotonic()-start
                samples.append({'elapsed_s':elapsed,'rss_mib':rss/1048576,'available_mib':m['MemAvailable']/1048576,'swap_growth_mib':max(0,m['swap_used']-base['swap_used'])/1048576})
                if elapsed>600:reason='time_guard';break
                if rss>1536*1048576 or m['MemAvailable']<2048*1048576 or m['swap_used']-base['swap_used']>256*1048576:reason='resource_guard';break
                time.sleep(.2)
        finally:
            if p.poll() is None:
                p.terminate()
                try:p.wait(timeout=10)
                except subprocess.TimeoutExpired:p.kill();p.wait()
    save(out/'supervisor.json',{'exit_code':p.returncode,'stop_reason':reason,'samples':samples,'elapsed_s':time.monotonic()-start})
    if reason or p.returncode:raise RuntimeError('Diagnostic failed; retained partial cells are not retried')
    print('Diagnostic completed; no transcript or routing change',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('pilot','worker'));parser.add_argument('manifest');args=parser.parse_args()
    (pilot if args.mode=='pilot' else worker)(args.manifest)
