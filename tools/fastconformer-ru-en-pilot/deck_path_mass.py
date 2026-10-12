"""Exact mass of two actually retained bilingual paths; no new transcript/search."""
import argparse
from functools import lru_cache
import json
import math
from pathlib import Path
import resource
import time
from ctc_context import NEG,logadd
from decoder import ContextBias
from giga_transducer import Model
from mms_pair import digest,save
from russian_boundary import NativeWordRules
from subword_pair import BOUNDARY
from run import Guard


def exact(events,seq,rules,encoded,lp,model,check,viterbi=False):
    import numpy as np
    combine=max if viterbi else logadd
    if any(not rules.allows(seq[:i],t) for i,t in enumerate(seq)):raise ValueError('Invalid retained path')
    russian=[()]
    for t in seq:russian.append(russian[-1]+((t-1025,) if t>=1025 else ()))
    @lru_cache(maxsize=None)
    def prediction(prefix):
        if not prefix:return model.predict(33,model.initial_states())
        _,s=prediction(prefix[:-1]);return model.predict(prefix[-1],s)
    @lru_cache(maxsize=50000)
    def probs(frame,prefix):
        p,_=prediction(prefix);r=model.join(encoded[:,:,frame:frame+1],p).astype(np.float64)
        return r-np.logaddexp.reduce(r)
    def score(cap):
        cur={0:(0.,NEG)}
        def add(dst,u,b=NEG,n=NEG):
            x,y=dst.get(u,(NEG,NEG));dst[u]=combine(x,b),combine(y,n)
        for ei,e in enumerate(events):
            check();nxt={};frame=e['native_frame']
            if e['head']=='eng':
                row=lp[frame]
                for u,(pb,pn) in cur.items():
                    total=combine(pb,pn);add(nxt,u,b=total+float(row[1024]));last=seq[u-1] if u else None
                    if last is not None and last<1025:add(nxt,u,n=pn+float(row[last]))
                    if u<len(seq) and seq[u]<1025:add(nxt,u+1,n=(pb if seq[u]==last else total)+float(row[seq[u]]))
            else:
                active=cur
                for depth in range((len(seq) if cap is None else cap)+1):
                    after={}
                    for u,(pb,pn) in active.items():
                        if not math.isfinite(combine(pb,pn)):continue
                        r=probs(frame,russian[u]);add(nxt,u,b=pb+float(r[33]),n=pn+float(r[33]))
                        if (cap is None or depth<cap) and u<len(seq) and seq[u]>=1025:add(after,u+1,n=combine(pb,pn)+float(r[seq[u]-1025]))
                    active=after
                    if not active:break
            if ei+1<len(events) and events[ei+1]['head']!=e['head']:
                nxt={u:v for u,v in nxt.items() if rules.can_leave_head(seq[:u],e['head'],events[ei+1]['head'])}
            cur=nxt
        return combine(*cur.get(len(seq),(NEG,NEG)))
    graph=ContextBias(rules.paths,2.5);state=();credit=0.
    for i in range(len(seq)):
        for symbol in rules.path_symbols(seq[:i+1]):delta,state=graph.step(state,symbol);credit+=delta
    delta,state=graph.step(state,BOUNDARY);credit+=delta+graph.finalize(state)
    a=score(10);b=None if viterbi else score(None)
    return {'objective':'viterbi' if viterbi else 'logsum','acoustic_mass_cap10':a,'acoustic_mass_uncapped':b,'context_credit':credit,'total_cap10':a+credit,'cache':probs.cache_info()._asdict()}


def main(args):
    import numpy as np
    import sentencepiece as spm
    cfg=json.loads(Path(args.manifest).read_text());base=Path(cfg['retained_inputs_directory']);em=Path(cfg['english_model']);ep=json.loads((em/'prepared.json').read_text());model=Model(Path(cfg['russian_model']));guard=Guard(600,1280);start=time.monotonic();clip='long'
    with np.load(base/(clip+'-eng.npz')) as f:lp=f['values'].astype(np.float64)
    with np.load(base/(clip+'-rus.npz')) as f:encoded=f['values']
    lp[:,0]=-np.inf;lp-=np.logaddexp.reduce(lp,axis=1,keepdims=True)
    align=json.loads((base/(clip+'-alignment.json')).read_text());rules=NativeWordRules({int(k):v for k,v in ep['vocab'].items()},{int(k):v for k,v in model.prepared['tokens'].items()},spm.SentencePieceProcessor(model_file=str(em/'tokenizer.model')),ep['english_case'])
    paths=json.loads(Path(args.paths).read_text());rows=[]
    for row in paths:
        r={'name':row['name'],**exact(align['selected_events'],row['token_ids'],rules,encoded,lp,model,guard.check,viterbi=args.viterbi)};rows.append(r);print(json.dumps(r),flush=True)
    save(Path(args.output),{'results':rows,'path_receipt_sha256':digest(args.paths),'alignment_sha256':digest(base/(clip+'-alignment.json')),'elapsed_s':time.monotonic()-start,'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,'guard':guard.receipt()})

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for key in ('manifest','paths','output'):p.add_argument('--'+key,required=True)
    p.add_argument('--viterbi',action='store_true')
    main(p.parse_args())
