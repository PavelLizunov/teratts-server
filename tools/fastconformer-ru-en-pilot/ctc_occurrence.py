"""Exact word-event probability under a saved CTC head, not word confidence.

Sum every raw alignment once using a deterministic spelling automaton and the
previous raw label. Covers all subword segmentations; never chooses a transcript.
"""
import itertools
import math
import unicodedata

BOUNDARY='\x01'


def symbols(text):
    result=[]
    for c in text.replace('▁',' '):
        sep=c.isspace() or (unicodedata.category(c)[0] in 'PZS' and c!="'")
        result.append(BOUNDARY if sep else c)
    return ''.join(result)


def pattern_for(text):
    parts=[p for p in symbols(text).split(BOUNDARY) if p]
    if not parts:raise ValueError('Empty word-event target')
    return BOUNDARY+BOUNDARY.join(parts)+BOUNDARY


def automaton(pieces,target):
    import numpy as np
    pattern=pattern_for(target);n=len(pattern)
    failure=[0]*n
    for i in range(1,n):
        j=failure[i-1]
        while j and pattern[i]!=pattern[j]:j=failure[j-1]
        if pattern[i]==pattern[j]:j+=1
        failure[i]=j

    def feed(state,chars):
        for c in chars:
            if state==n:return n
            # Consecutive punctuation/separators denote one word boundary.
            if c==BOUNDARY and state and pattern[state-1]==BOUNDARY:continue
            while state and pattern[state]!=c:state=failure[state-1]
            if pattern[state]==c:state+=1
        return state

    transitions=np.array([[feed(q,symbols(p)) for p in pieces] for q in range(n)],dtype=np.int32)
    eof=np.array([feed(q,BOUNDARY)==n for q in range(n)])
    return transitions,eof,pattern


def occurrence(log_probs,pieces,blank,target,check=lambda:None):
    import numpy as np
    lp=np.asarray(log_probs,dtype=np.float64)
    if lp.ndim!=2 or lp.shape[1]!=len(pieces) or not 0<=blank<len(pieces):raise ValueError('CTC shape/vocabulary mismatch')
    if np.isnan(lp).any() or np.isposinf(lp).any():raise ValueError('Nonfinite CTC input')
    row_error=float(np.max(np.abs(np.logaddexp.reduce(lp,axis=1))))
    if row_error>1e-8:raise ValueError('Unnormalized CTC rows')
    transitions,eof,pattern=automaton(pieces,target)
    count=transitions.shape[0];vocab=len(pieces);tokens=np.array([v for v in range(vocab) if v!=blank])
    dst=transitions[:,tokens];cols=np.broadcast_to(tokens,dst.shape)
    found_mask=dst==count;live=~found_mask
    current=np.full((count,vocab),-np.inf);current[1,blank]=0.
    found=-math.inf;first=[];maximum_error=0.
    for frame,row in enumerate(lp):
        check()
        total=np.logaddexp.reduce(current,axis=1)
        following=np.full_like(current,-np.inf)
        following[:,blank]=total+row[blank]
        following[:,tokens]=current[:,tokens]+row[tokens]
        # Stable exclude-one sums: no subtraction of almost equal probabilities.
        left=np.logaddexp.accumulate(current,axis=1)
        right=np.logaddexp.accumulate(current[:,::-1],axis=1)[:,::-1]
        exclude=np.full_like(current,-np.inf)
        exclude[:,1:]=left[:,:-1]
        exclude[:,:-1]=np.logaddexp(exclude[:,:-1],right[:,1:])
        emitted=exclude[:,tokens]+row[tokens]
        np.logaddexp.at(following,(dst[live],cols[live]),emitted[live])
        hit=float(np.logaddexp.reduce(emitted[found_mask])) if found_mask.any() else -math.inf
        found=float(np.logaddexp(found,hit));first.append(hit)
        total_mass=float(np.logaddexp(found,np.logaddexp.reduce(following.ravel())))
        maximum_error=max(maximum_error,abs(total_mass))
        if abs(total_mass)>1e-8:raise ValueError('CTC event mass not conserved')
        current=following
    end=float(np.logaddexp.reduce(current[eof].ravel())) if eof.any() else -math.inf
    logp=float(np.logaddexp(found,end));p=math.exp(logp) if math.isfinite(logp) else 0.
    if logp>1e-8:raise ValueError('Word event probability above one')
    return {'target':target,'probability':p,'log_probability':logp if math.isfinite(logp) else None,
            'first_completion_log_mass':[v if math.isfinite(v) else None for v in first],
            'eof_completion_log_mass':end if math.isfinite(end) else None,
            'maximum_log_total_mass_error':maximum_error,'row_normalization_error':row_error,
            'dfa_states':count,'frames':len(lp),'all_segmentations':True,
            'whole_word_boundaries':True,'acoustic_distribution_not_calibrated_confidence':True}


def enumerate_controls():
    """New algorithm controls with independent raw-path enumeration, not audio."""
    import numpy as np
    rows=[]
    cases=[(['▁a','b',''],2,5,['a','ab','bb','a a','a b','ba']),
           (['▁a','a','▁aa',''],3,4,['a','aa','aaa','a aa'])]
    for pieces,blank,frames,targets in cases:
        weights=np.arange(1,frames*len(pieces)+1,dtype=np.float64).reshape(frames,-1)
        weights=weights/weights.sum(axis=1,keepdims=True)
        for target in targets:
            expected=0.;paths=0
            for raw in itertools.product(range(len(pieces)),repeat=frames):
                output=[];previous=blank
                for token in raw:
                    if token!=previous and token!=blank:output.append(pieces[token])
                    previous=token
                # Separate direct string event checker; no DFA/DP reuse.
                words=' '.join(''.join(output).replace('▁',' ').split())
                if (' '+target+' ') in (' '+words+' '):
                    expected+=math.prod(weights[t,token] for t,token in enumerate(raw));paths+=1
            actual=occurrence(np.log(weights),pieces,blank,target)
            error=abs(actual['probability']-expected)
            rows.append({'pieces':pieces,'frames':frames,'target':target,'enumerated_paths':len(pieces)**frames,
                         'matching_paths':paths,'enumerated_probability':expected,'dp_probability':actual['probability'],'absolute_error':error})
            if error>1e-12:raise ValueError('Exact enumeration disagrees with occurrence DP')
    return rows
