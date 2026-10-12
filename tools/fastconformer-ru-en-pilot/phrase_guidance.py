"""Auxiliary English CTC phrase timing with unconstrained gaps.

Only timing reaches the final open trained-head search. The saved auxiliary
proposal is not a reference transcript and Russian words are not forced here.
"""
import argparse
import math

from subword_pair import main


def align_phrases(events,sequence,check):
    import numpy as np
    phrases=[];previous=None
    for lang,token in sequence:
        if lang=='eng':
            if previous!='eng':phrases.append([])
            phrases[-1].append(token)
        previous=lang
    if not phrases:raise ValueError('No auxiliary English phrase')
    native=[e for e in events if e['head']=='eng']
    # Each state owns the observation it emits, including a wildcard gap frame.
    states=[{'kind':'gap','phrase':None,'token':None,'label':None,'predecessors':[]}]
    gap=0;coverage_count=0;terminals=[]
    for phrase_id,labels in enumerate(phrases):
        last_label=None;last_blank=None
        for j,token in enumerate(labels):
            predecessors=[gap] if j==0 else [last_blank]
            if last_label is not None and token!=labels[j-1]:predecessors.append(last_label)
            states.append({'kind':'label','phrase':phrase_id,'token':token,'label':coverage_count,'predecessors':predecessors})
            last_label=len(states)-1;coverage_count+=1
            states.append({'kind':'blank','phrase':phrase_id,'token':1024,'label':None,'predecessors':[last_label]})
            last_blank=len(states)-1
        terminals=[last_label,last_blank]
        states.append({'kind':'gap','phrase':None,'token':None,'label':None,'predecessors':terminals})
        gap=len(states)-1
    count=len(states);best=np.full(count,-np.inf);best[0]=0.;parents=[]
    for event in native:
        check();row=event['log_probs'];maximum=float(row.max());following=np.full(count,-np.inf);parent=np.empty(count,np.int32)
        for i,state in enumerate(states):
            source=max([i,*state['predecessors']],key=lambda s:best[s])
            cost=0. if state['kind']=='gap' else float(row[state['token']])-maximum
            following[i]=best[source]+cost;parent[i]=source
        best=following;parents.append(parent)
    terminal=max([gap,*terminals],key=lambda s:best[s]);score=float(best[terminal])
    if not math.isfinite(score):raise ValueError('No complete ordered phrase path')
    trace=[];spans=[[] for _ in phrases];coverage=set();state_id=terminal;backtrace=0.
    for i in range(len(native)-1,-1,-1):
        state=states[state_id];source=int(parents[i][state_id]);event=native[i]
        cost=0. if state['kind']=='gap' else float(event['log_probs'][state['token']]-event['log_probs'].max())
        backtrace+=cost
        if state['phrase'] is not None:spans[state['phrase']].append(event['native_frame'])
        if state['label'] is not None:coverage.add(state['label'])
        trace.append({'native_frame':event['native_frame'],'center_s':event['center_s'],'kind':state['kind'],'phrase':state['phrase'],
                      'local_token':state['token'],'label':state['label'],'relative_score':cost,'state':state_id,'source_state':source})
        state_id=source
    trace.reverse()
    if state_id!=0 or coverage!=set(range(coverage_count)) or any(not x for x in spans):raise ValueError('Incomplete auxiliary phrase coverage')
    if abs(score-backtrace)>1e-7:raise ValueError('Phrase backtrace score mismatch')
    intervals=[{'phrase':j,'first_en_frame':min(span),'last_en_frame':max(span),'start_s':max(0.,min(span)*.08-.04),'end_s':max(span)*.08+.04} for j,span in enumerate(spans)]
    def is_english(event):return any(x['start_s']<=event['center_s']<x['end_s'] for x in intervals)
    selected=[event for event in events if (event['head']=='eng')==is_english(event)]
    if len({(e['head'],e['native_frame']) for e in selected})!=len(selected):raise ValueError('Repeated native evidence')
    return selected,{'objective':'ordered English phrase CTC Viterbi relative to wildcard per-frame maximum; not calibrated language confidence',
                     'score':score,'backtrace_score_error':abs(score-backtrace),'english_phrases':phrases,'english_phrase_intervals':intervals,
                     'english_trace':trace,'labels_covered':coverage_count,'russian_words_forced':False,
                     'selected_events':[{k:e[k] for k in ('head','native_frame','center_s')} for e in selected],
                     'ignored_inactive_events':len(events)-len(selected),
                     'native_rows':{lang:sum(e['head']==lang for e in selected) for lang in ('eng','rus')}}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for key in ('russian','english','proposals','russian-model','english-model','output'):parser.add_argument('--'+key,required=True)
    main(parser.parse_args(),alignment_fn=align_phrases)
