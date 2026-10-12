"""Native RNNT/RU-CTC forced language routing; final mixed search stays open."""
import argparse
from functools import lru_cache
import math

from ctc_lm import pilot
from mixed_transducer import cell


def alignment(old,encoded,ru_logp,model,check):
    import numpy as np
    sequence=[tuple(x) for x in old['label_path']];n=len(sequence)
    english=[()]
    for lang,t in sequence:english.append(english[-1]+((t,) if lang=='eng' else ()))
    @lru_cache(maxsize=None)
    def prediction(prefix):
        if not prefix:return model.predict(1024,model.initial_states())
        _,state=prediction(prefix[:-1]);return model.predict(prefix[-1],state)
    @lru_cache(maxsize=None)
    def row(frame,prefix):
        pred,_=prediction(prefix)
        logits=model.join(encoded[:,:,frame:frame+1],pred).astype(np.float64)
        logits[0]=-np.inf
        return logits-np.logaddexp.reduce(logits)
    events=[]
    for lang,length,stride,origin in (('eng',encoded.shape[2],1280,0.),('rus',len(ru_logp),640,159.5)):
        events.extend({'head':lang,'native_frame':i,'center_s':(stride*i+origin)/16000} for i in range(length))
    events.sort(key=lambda e:e['center_s'])
    # Russian blank/nonblank bit is relevant only while Russian is active.
    initial=(0,sequence[0][0],True);best={initial:0.};parents=[]
    for event in events:
        check();lang=event['head'];frame=event['native_frame'];following={};parent={}
        def offer(key,value,source,detail):
            if value>following.get(key,-math.inf):
                following[key]=value;parent[key]=(source,detail)
        for source,value in best.items():
            u,head,blank=source
            same=lang==head
            switch=(not same and u<n and u>0 and sequence[u][0]==lang and sequence[u-1][0]==head)
            if not same:offer(source,value,source,None)
            if not same and not switch:continue
            if lang=='rus':
                probs=ru_logp[frame];last=sequence[u-1] if u else None
                def emit(v,b,token,kind,new_labels):
                    cost=float(probs[token]);detail={**event,'emissions':[token],'label_indices':new_labels,'kind':kind,'weighted_log_probability':cost,'switch':switch}
                    offer((v,'rus',b),value+cost,source,detail)
                emit(u,True,33,'blank',[])
                if same and not blank and last is not None and last[0]=='rus':emit(u,False,last[1],'repeat',[])
                if u<n and sequence[u][0]=='rus' and (switch or blank or last!=sequence[u]):emit(u+1,False,sequence[u][1],'label',[u])
            else:
                total=value;emissions=[];indices=[]
                for depth in range(11):
                    v=u+depth;probs=row(frame,english[v]);cost=total-value+2.*float(probs[1024])
                    detail={**event,'emissions':emissions+[1024],'label_indices':list(indices),'kind':'rnnt','weighted_log_probability':cost,'switch':switch}
                    offer((v,'eng',True),value+cost,source,detail)
                    if depth==10 or v==n or sequence[v][0]!='eng':break
                    token=sequence[v][1];total+=2.*float(probs[token]);emissions.append(token);indices.append(v)
        best=following;parents.append(parent)
    choices=[s for s in best if s[0]==n]
    if not choices:raise ValueError('No complete RNNT/CTC alignment')
    terminal=max(choices,key=lambda s:best[s]);score=best[terminal]
    if not math.isfinite(score):raise ValueError('No finite native alignment')
    state=terminal;trace=[];coverage=[];backtrace=0.
    for i in range(len(events)-1,-1,-1):
        previous,detail=parents[i][state]
        if detail is not None:
            trace.append({**detail,'union_event':i,'source_state':list(previous),'state':list(state)})
            coverage.extend(detail['label_indices']);backtrace+=detail['weighted_log_probability']
        state=previous
    trace.reverse()
    if state!=initial or sorted(coverage)!=list(range(n)):raise ValueError('Incomplete or repeated auxiliary labels')
    if abs(score-backtrace)>1e-7:raise ValueError('Native alignment backtrace disagreement')
    switches=[]
    for i,t in enumerate(trace):
        if i and t['head']!=trace[i-1]['head']:
            switches.append({'from':trace[i-1]['head'],'to':t['head'],'old_last_center_s':trace[i-1]['center_s'],'new_first_center_s':t['center_s']})
    old_set={(x['head'],x['native_frame']) for x in old['selected_events']};new_set={(x['head'],x['native_frame']) for x in trace}
    return {'objective':'duration-weighted native RNNT/Russian CTC auxiliary Viterbi, not calibrated joint probability',
            'stride_weights':{'eng':2.,'rus':1.},'rnnt_max_symbols':10,'score':score,'backtrace_score_error':abs(score-backtrace),
            'label_path':sequence,'selected_events':trace,'switches':switches,'old_ctc_switches':old['switches'],
            'labels_covered':len(coverage),'ignored_inactive_events':len(events)-len(trace),
            'native_rows':{lang:sum(x['head']==lang for x in trace) for lang in ('eng','rus')},
            'added_native_events':[{'head':lang,'native_frame':frame} for lang,frame in sorted(new_set-old_set)],
            'removed_native_events':[{'head':lang,'native_frame':frame} for lang,frame in sorted(old_set-new_set)]}


if __name__=='__main__':
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='mode',required=True);c=sub.add_parser('cell')
    for key in ('root','model','receipt','context-receipt','output'):c.add_argument('--'+key,required=True)
    p=sub.add_parser('pilot');p.add_argument('manifest');args=parser.parse_args()
    if args.mode=='cell':cell(args,alignment_fn=alignment)
    else:pilot(args,cell_script=__file__)
