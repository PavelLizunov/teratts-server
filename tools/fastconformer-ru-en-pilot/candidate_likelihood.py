"""Freeze and supervise native per-candidate conditional text scoring."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import time

from mms_pair import digest, save
from mini_editor import EDIT_SYSTEM, normalized
from pilot import rss_bytes
from run import memory_snapshot


def prepare(root,result_name='likelihood-sequential'):
    from jinja2.sandbox import ImmutableSandboxedEnvironment
    directory=root/result_name;directory.mkdir(exist_ok=False)
    suite=json.loads((root/'suite.json').read_text());corpus=json.loads((root/'corpus-order-suite.json').read_text());extra=json.loads((root/'corpus-suite.json').read_text())
    rows=suite['rows']+corpus['rows']+[r for r in extra['rows'] if r['kind']=='synthetic_text_control']
    props=json.loads((root/'results-qwen3/server-props.json').read_text());template=ImmutableSandboxedEnvironment(trim_blocks=True,lstrip_blocks=True).from_string(props['chat_template'])
    def prefix(text):
        return template.render(messages=[{'role':'system','content':EDIT_SYSTEM},{'role':'user','content':'<transcript>\n'+text+'\n</transcript>'}],tools=None,add_generation_prompt=True,enable_thinking=False)
    # Preserve exact template, rendered prompt and candidate text independently.
    requests=[{'purpose':'causal_prefix','prefix':prefix('Не включай режим B.'),'answer':'Не включай режим B.','chunk':1},
              {'purpose':'causal_prefix_with_suffix','prefix':prefix('Не включай режим B.'),'answer':'Не включай режим B. Используй режим C.','chunk':1}]
    cache={}
    for row in rows:
        if row.get('source') and digest(row['source'])!=row['source_sha256']:raise ValueError('Changed saved ASR receipt')
        row['prefix']=prefix(row['input']);row['score_request_indices']={}
        for candidate in sorted(set(row['candidates'])):
            key=(row['prefix'],candidate)
            if key not in cache:
                cache[key]=len(requests);requests.append({'purpose':'candidate','prefix':row['prefix'],'answer':candidate,'chunk':1})
            row['score_request_indices'][candidate]=cache[key]
    manifest={'model_sha256':'9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031','rows':rows,'requests':requests,
              'primary_score':'mean target log probability including im_end','sum_is_diagnostic_only':True,'template':props['chat_template'],
              'source_suites':{n:digest(root/n) for n in ('suite.json','corpus-order-suite.json','corpus-suite.json')},'audio_inference':False}
    save(directory/'manifest.json',manifest)
    def pack(s):
        b=s.encode();return struct.pack('<I',len(b))+b
    with (directory/'input.bin').open('xb') as f:
        f.write(struct.pack('<I',len(requests)))
        for r in requests:f.write(pack(r['prefix'])+pack(r['answer'])+struct.pack('<I',r['chunk']))
    print('Frozen cases',len(rows),'unique candidate scores',len(requests)-2,'numerical smoke passes',2)


def run(root,result_name='likelihood-sequential'):
    directory=root/result_name;manifest=json.loads((directory/'manifest.json').read_text());binary=root/'likelihood-native/candidate-likelihood-sequential';model=root/'qwen3-q8.gguf'
    if digest(model)!=manifest['model_sha256']:raise ValueError('Model changed')
    output=directory/'scores.jsonl'
    if output.exists():raise FileExistsError('Refusing repeated or unknown scoring cells')
    cmd=[str(binary),str(model),str(directory/'input.bin'),str(output),str(root/'runtime/llama-b11429')]
    initial=memory_snapshot();samples=[];start=time.monotonic();proc=None
    result={'status':'failed','command':cmd,'binary_sha256':digest(binary),'manifest_sha256':digest(directory/'manifest.json'),'model_sha256':manifest['model_sha256'],'initial_memory':initial,'samples':samples}
    try:
        if initial['MemAvailable']<2048*1048576:raise MemoryError('Available floor before launch')
        with (directory/'native.log').open('x') as log:
            proc=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT)
            while proc.poll() is None:
                mem=memory_snapshot();rss=rss_bytes(proc.pid);elapsed=time.monotonic()-start
                samples.append({'elapsed_s':elapsed,'rss_bytes':rss,'available_bytes':mem['MemAvailable'],'swap_growth_bytes':max(0,mem['swap_used']-initial['swap_used'])})
                if elapsed>900:raise TimeoutError('Overall scorer limit')
                if rss>3072*1048576 or mem['MemAvailable']<2048*1048576 or mem['swap_used']-initial['swap_used']>256*1048576:raise MemoryError('Scoring memory guard')
                time.sleep(.2)
        result['returncode']=proc.returncode
        if proc.returncode!=0:raise RuntimeError('Native scorer returned '+str(proc.returncode))
        scored=[json.loads(line) for line in output.read_text().splitlines()]
        if len(scored)!=len(manifest['requests']) or [x['index'] for x in scored]!=list(range(len(scored))):raise ValueError('Incomplete native evidence')
        result['scores_sha256']=digest(output);rows=[]
        for row in manifest['rows']:
            candidates=[]
            for candidate in row['candidates']:
                r=scored[row['score_request_indices'][candidate]]
                candidates.append({'text':candidate,'mean_logprob':r['mean_logprob'],'sum_logprob':r['sum_logprob'],'target_tokens':len(r['target_logprobs']),'elapsed_s':r['elapsed_s'],'request_index':r['index']})
            best=max(c['mean_logprob'] for c in candidates);winners=sorted(set(c['text'] for c in candidates if abs(c['mean_logprob']-best)<=1e-6))
            chosen=winners[0] if len(winners)==1 else None
            record={'id':row['id'],'kind':row['kind'],'input':row['input'],'reference':row['reference'],'candidates':candidates,'winner_texts':winners,'selected_text':chosen,
                    'normalized_equal_reference':None if row['reference'] is None or chosen is None else normalized(chosen)==normalized(row['reference']),
                    'normalized_equal_input':None if chosen is None else normalized(chosen)==normalized(row['input']),
                    'protected_missing':None if chosen is None else [x for x in row['protected'] if x.casefold() not in chosen.casefold()],
                    'negative_tokens_before_after':None if chosen is None else [sum(t in ('не','нет','без','not','no') for t in normalized(x)) for x in (row['input'],chosen)],
                    'evaluation_s':sum(scored[i]['elapsed_s'] for i in set(row['score_request_indices'].values()))}
            save(directory/(row['id']+'.json'),record);rows.append(record)
        result['rows']=rows
        shared=next((i for i,(a,b) in enumerate(zip(scored[0]['token_ids'],scored[1]['token_ids'])) if a!=b),min(len(scored[0]['token_ids']),len(scored[1]['token_ids'])))
        targets=shared-scored[0]['prefix_tokens'];result['causal_smoke_shared_targets']=targets
        result['causal_smoke_max_difference']=max(abs(a-b) for a,b in zip(scored[0]['target_logprobs'][:targets],scored[1]['target_logprobs'][:targets]));result['status']='success'
        print('Completed',len(rows),'cases; controls',sum(r['normalized_equal_reference'] is True for r in rows),'/',sum(r['reference'] is not None for r in rows))
    except Exception as error:result['error']=type(error).__name__+': '+str(error);raise
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
        result.update(elapsed_s=time.monotonic()-start,returncode=proc.returncode if proc else None);save(directory/'summary.json',result)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('prepare','run'));p.add_argument('root',type=Path);p.add_argument('--result-name',default='likelihood-sequential');a=p.parse_args()
    if a.mode=='prepare':prepare(a.root,a.result_name)
    else:run(a.root,a.result_name)
