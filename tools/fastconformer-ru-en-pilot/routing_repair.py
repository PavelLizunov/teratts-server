"""One causal timing-extraction repair; reuses unchanged final paths verbatim."""
import argparse
import json
from pathlib import Path
import resource
import subprocess
import time

from english_timing import english_timing_labels
from mms_pair import digest, save
from phrase_guidance import align_phrases
from run import Guard, memory_snapshot
from pilot import rss_bytes


def cell(manifest_path,clip):
    import numpy as np
    import sentencepiece as spm
    from giga_transducer import Model
    from russian_boundary import NativeWordRules
    from state_transducer import search
    cfg=json.loads(Path(manifest_path).read_text());row=next(r for r in cfg['recordings'] if r['id']==clip)
    output=Path(cfg['output'])/(clip+'.json');start=time.monotonic();guard=Guard(600,1536)
    result={'id':clip,'status':'failed','encoder_rerun':False,'audio_modified':False,'new_decoder_run':False,'source_commit':cfg['source_commit']}
    try:
        receipts={k:json.loads(Path(row[k]).read_text()) for k in ('aux','eng','rus')}
        for key in receipts:
            if digest(row[key])!=row['hashes'][key]:raise ValueError('Changed retained receipt')
        if len({r['audio_sha256'] for r in receipts.values()})!=1:raise ValueError('Different original audio sources')
        result['audio_sha256']=receipts['eng']['audio_sha256']
        for h in ('eng','rus'):
            if digest(Path(row[h]).with_suffix('.npz'))!=receipts[h]['retained_array_sha256']:raise ValueError('Changed retained acoustic data')
        em=Path(cfg['english_model']);rm=Path(cfg['russian_model']);ep=json.loads((em/'prepared.json').read_text());rp=json.loads((rm/'prepared.json').read_text())
        if digest(em/'prepared.json')!=receipts['eng']['prepared_sha256'] or digest(rm/'prepared.json')!=receipts['rus']['prepared_sha256']:raise ValueError('Different trained model mapping')
        if digest(em/'tokenizer.model')!=ep['tokenizer_sha256']:raise ValueError('Changed English tokenizer')
        sp=spm.SentencePieceProcessor(model_file=str(em/'tokenizer.model'))
        text=receipts['aux']['hypotheses'][0]['raw_text'];result['auxiliary_raw_text']=text
        try:sequence,words=english_timing_labels(text,sp,ep['english_case'])
        except ValueError as error:
            result.update(status='unsupported_auxiliary',error=str(error));return
        result.update(auxiliary_sequence=sequence,auxiliary_words=words)
        with np.load(Path(row['eng']).with_suffix('.npz')) as f:lp=f['values'].astype(np.float64)
        with np.load(Path(row['rus']).with_suffix('.npz')) as f:encoded=f['values']
        lp[:,0]=-np.inf;lp-=np.logaddexp.reduce(lp,axis=1,keepdims=True)
        events=[{'head':'eng','native_frame':i,'center_s':i*.08,'log_probs':v} for i,v in enumerate(lp)]
        events.extend({'head':'rus','native_frame':i,'center_s':i*.04+rp['nominal_origin_s']} for i in range(encoded.shape[-1]));events.sort(key=lambda e:e['center_s'])
        before=time.monotonic()
        try:selected,alignment=align_phrases(events,sequence,guard.check)
        except ValueError as error:
            result.update(status='unalignable_auxiliary',error=str(error));return
        result.update(alignment=alignment,alignment_s=time.monotonic()-before)
        if row.get('old_alignment'):
            if digest(row['old_alignment'])!=row['hashes']['old_alignment']:raise ValueError('Old routing changed')
            old=json.loads(Path(row['old_alignment']).read_text())
            same=alignment['selected_events']==old['selected_events'];result['selected_events_identical']=same
            if not same:raise ValueError('Unexpected route regression; do not run changed successful row')
            if not row.get('old_final'):raise ValueError('Missing successful old decoder receipt')
            if digest(row['old_final'])!=row['hashes']['old_final']:raise ValueError('Old final changed')
            final=json.loads(Path(row['old_final']).read_text())
            if final['status']!='success':raise ValueError('Old aligned record lacked successful decoder')
            result.update(status='reused_unchanged',reused_final_sha256=digest(row['old_final']),search=final['search'],runtime_origin='saved Deck result, no rerun');return
        model=Model(rm);tokens={int(k):v for k,v in rp['tokens'].items()};rules=NativeWordRules({int(k):v for k,v in ep['vocab'].items()},tokens,sp,ep['english_case'])
        before=time.monotonic();result['new_decoder_run']=True
        result['search']=search(selected,encoded,lp,model,rules,2.5,guard.check,same_text_logsum=True)
        if not result['search']['hypotheses']:raise ValueError('No complete constrained output')
        result.update(decode_s=time.monotonic()-before,status='new_constrained_output',runtime_origin='local host joiner/predictor with retained Deck encoder output',formatting=rules.formatting)
        import onnxruntime as ort
        result['onnxruntime']=ort.__version__
    except Exception as error:result.update(error=type(error).__name__+': '+str(error));raise
    finally:
        result.update(elapsed_s=time.monotonic()-start,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,guard=guard.receipt(),source_hashes=row['hashes'])
        save(output,result)


def pilot(manifest_path):
    cfg=json.loads(Path(manifest_path).read_text());out=Path(cfg['output']);out.mkdir(exist_ok=False,mode=0o700)
    for name,sha in cfg['source_files'].items():
        if digest(Path(__file__).parent/name)!=sha:raise ValueError('Changed frozen source')
    started=time.monotonic();allrows=[]
    for r in cfg['recordings']:
        if time.monotonic()-started>900:raise TimeoutError('Frozen batch deadline')
        cmd=[cfg['python'],str(Path(__file__).resolve()),'cell',str(manifest_path),'--clip',r['id']];baseline=memory_snapshot();begin=time.monotonic();samples=[];reason=None
        with (out/(r['id']+'.log')).open('x') as log:
            process=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT)
            try:
                while process.poll() is None:
                    m=memory_snapshot();rss=rss_bytes(process.pid)
                    samples.append({'elapsed_s':time.monotonic()-begin,'rss_bytes':rss,'available_bytes':m['MemAvailable'],'swap_growth_bytes':max(0,m['swap_used']-baseline['swap_used'])})
                    if rss>1536*1048576 or m['MemAvailable']<2048*1048576 or m['swap_used']-baseline['swap_used']>256*1048576:reason='resource_guard';break
                    if time.monotonic()-begin>600 or time.monotonic()-started>900:reason='time_guard';break
                    time.sleep(.2)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
        receipt={'id':r['id'],'returncode':process.returncode,'stop_reason':reason,'elapsed_s':time.monotonic()-begin,'samples':samples,'command':cmd}
        save(out/(r['id']+'-supervisor.json'),receipt);allrows.append(receipt)
        if reason or process.returncode:
            save(out/'supervisor-summary.json',{'rows':allrows,'status':'failed','elapsed_s':time.monotonic()-started});raise RuntimeError('Stopped dependent branch; preserve consumed results')
        actual=json.loads((out/(r['id']+'.json')).read_text());print(r['id'],actual['status'],actual.get('decode_s'),flush=True)
    save(out/'supervisor-summary.json',{'rows':allrows,'status':'completed','elapsed_s':time.monotonic()-started})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('pilot','cell'));p.add_argument('manifest');p.add_argument('--clip');a=p.parse_args()
    if a.mode=='cell':cell(a.manifest,a.clip)
    else:pilot(a.manifest)
