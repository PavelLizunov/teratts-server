"""One causal timing-extraction repair; reuses unchanged final paths verbatim."""
import argparse
import json
import math
from pathlib import Path
import resource
import subprocess
import time

from acoustic_cache import array_identity, reuse_identity
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
    output=Path(cfg['output'])/(clip+'.json')
    if output.exists():raise FileExistsError('Consumed/unknown routing cell')
    method=cfg.get('timing_method','english-only')
    if method not in ('english-only','ctc-corroborated-words-v1'):raise ValueError('Unknown timing method')
    context_mode=cfg.get('context_mode','global-fixed')
    if context_mode not in ('global-fixed','auxiliary-interval-v1','auxiliary-spelling-interval-v1'):raise ValueError('Unknown context mode')
    retain_graph=bool(cfg.get('retain_context_graph',False))
    bonus=float(cfg.get('context_score',2.5))
    if not math.isfinite(bonus) or bonus<0:raise ValueError('Invalid context score')
    start=time.monotonic();guard=Guard(600,1536)
    result={'id':clip,'status':'failed','timing_method':method,'encoder_rerun':False,'audio_modified':False,'new_decoder_run':False,'source_commit':cfg['source_commit'],'context_score':bonus,'retain_context_graph':retain_graph,'context_mode':context_mode}
    try:
        receipts={k:json.loads(Path(row[k]).read_text()) for k in ('aux','eng','rus')}
        for key in receipts:
            if digest(row[key])!=row['hashes'][key]:raise ValueError('Changed retained receipt')
        if len({r['audio_sha256'] for r in receipts.values()})!=1:raise ValueError('Different original audio sources')
        result['audio_sha256']=receipts['eng']['audio_sha256']
        identities={h:array_identity(receipts[h]) for h in ('eng','rus')}
        for h in ('eng','rus'):
            if digest(Path(row[h]).with_suffix('.npz'))!=identities[h][1]:raise ValueError('Changed retained acoustic data')
        result['acoustic_identity']={h:{'receipt_sha256':row['hashes'][h],'prepared_sha256':receipts[h]['prepared_sha256'],
                                      'array_sha256':identities[h][1],'array_key':identities[h][0]} for h in ('eng','rus')}
        em=Path(cfg['english_model']);rm=Path(cfg['russian_model']);ep=json.loads((em/'prepared.json').read_text());rp=json.loads((rm/'prepared.json').read_text())
        if digest(em/'prepared.json')!=receipts['eng']['prepared_sha256'] or digest(rm/'prepared.json')!=receipts['rus']['prepared_sha256']:raise ValueError('Different trained model mapping')
        if digest(em/'tokenizer.model')!=ep['tokenizer_sha256']:raise ValueError('Changed English tokenizer')
        sp=spm.SentencePieceProcessor(model_file=str(em/'tokenizer.model'))
        text=receipts['aux']['hypotheses'][0]['raw_text'];result['auxiliary_raw_text']=text
        try:sequence,words=english_timing_labels(text,sp,ep['english_case'])
        except ValueError as error:
            result.update(status='unsupported_auxiliary',error=str(error));return
        result.update(auxiliary_sequence=sequence,auxiliary_words=words)
        with np.load(Path(row['eng']).with_suffix('.npz')) as f:lp=f[identities['eng'][0]].astype(np.float64)
        with np.load(Path(row['rus']).with_suffix('.npz')) as f:encoded=f[identities['rus'][0]]
        lp[:,0]=-np.inf;lp-=np.logaddexp.reduce(lp,axis=1,keepdims=True)
        if method=='ctc-corroborated-words-v1':
            from corroborated_timing import corroborated_sequence
            sequence,corroboration=corroborated_sequence(words,lp,sp,ep['english_case'])
            result.update(corroboration=corroboration,auxiliary_sequence=sequence)
        events=[{'head':'eng','native_frame':i,'center_s':i*.08,'log_probs':v} for i,v in enumerate(lp)]
        events.extend({'head':'rus','native_frame':i,'center_s':i*.04+rp['nominal_origin_s']} for i in range(encoded.shape[-1]));events.sort(key=lambda e:e['center_s'])
        before=time.monotonic()
        try:selected,alignment=align_phrases(events,sequence,guard.check)
        except ValueError as error:
            result.update(status='unalignable_auxiliary',error=str(error));return
        result.update(alignment=alignment,alignment_s=time.monotonic()-before)
        prior=None;prior_path=None
        if row.get('prior_result'):
            prior_path=row['prior_result']
            if digest(prior_path)!=row['hashes']['prior_result']:raise ValueError('Prior experiment changed')
            prior=json.loads(Path(prior_path).read_text())
            old=prior.get('alignment')
        elif row.get('old_alignment'):
            if digest(row['old_alignment'])!=row['hashes']['old_alignment']:raise ValueError('Old routing changed')
            old=json.loads(Path(row['old_alignment']).read_text())
            prior_path=row['old_final']
            if digest(prior_path)!=row['hashes']['old_final']:raise ValueError('Old final changed')
            prior=json.loads(Path(prior_path).read_text())
        else:old=None
        if cfg.get('require_prior_route',False) and old is None:raise ValueError('Missing required prior route')
        if old is not None:
            same=alignment['selected_events']==old['selected_events'];result['selected_events_identical']=same
            if cfg.get('require_prior_route',False) and not same:raise ValueError('Changed route in fixed-route comparison')
            if method=='english-only' and not same and not (cfg.get('auxiliary_replaced',False) or cfg.get('acoustic_replaced',False)):raise ValueError('Unexpected route regression')
            result['prior_context_score']=prior.get('search',{}).get('context_score')
            reuse_reason=reuse_identity(prior,row['hashes'],alignment['selected_events'],context_mode)
            result['prior_acoustic_reuse_reason']=reuse_reason
            if same and reuse_reason and prior.get('search',{}).get('context_score')==bonus and prior['search'].get('retain_context_graph',False)==retain_graph and prior['search'].get('context_mode','global-fixed')==context_mode and (context_mode=='global-fixed' or old['english_phrases']==alignment['english_phrases']):
                if not prior.get('search',{}).get('hypotheses'):raise ValueError('No previous complete output to reuse')
                result.update(status='reused_unchanged',reused_final_sha256=digest(prior_path),search=prior['search'],runtime_origin='saved earlier result, no rerun');return
        for candidate in row.get('reuse_results',[]):
            if digest(candidate['path'])!=candidate['sha256']:raise ValueError('Changed route reuse receipt')
            retained=json.loads(Path(candidate['path']).read_text())
            if retained['audio_sha256']!=result['audio_sha256']:raise ValueError('Route cache belongs to different audio')
            same=alignment['selected_events']==retained.get('alignment',{}).get('selected_events')
            reuse_reason=reuse_identity(retained,row['hashes'],alignment['selected_events'],context_mode)
            if same and reuse_reason and retained.get('search',{}).get('hypotheses') and retained['search'].get('context_score')==bonus and retained['search'].get('retain_context_graph',False)==retain_graph and retained['search'].get('context_mode','global-fixed')==context_mode and (context_mode=='global-fixed' or retained['alignment']['english_phrases']==alignment['english_phrases']):
                result.update(status='reused_prior_route',reused_final_sha256=candidate['sha256'],reused_result=candidate['path'],acoustic_reuse_reason=reuse_reason,search=retained['search'],runtime_origin='another previously consumed identical route, no rerun');return
        model=Model(rm);tokens={int(k):v for k,v in rp['tokens'].items()};rules=NativeWordRules({int(k):v for k,v in ep['vocab'].items()},tokens,sp,ep['english_case'])
        before=time.monotonic();result['new_decoder_run']=True
        result['search']=search(selected,encoded,lp,model,rules,bonus,guard.check,same_text_logsum=True,retain_context_graph=retain_graph,interval_alignment=alignment if context_mode!='global-fixed' else None,spelling_context=context_mode=='auxiliary-spelling-interval-v1')
        if not result['search']['hypotheses']:raise ValueError('No complete constrained output')
        result.update(decode_s=time.monotonic()-before,status='new_constrained_output',runtime_origin='local host joiner/predictor with retained native acoustic arrays',formatting=rules.formatting)
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
