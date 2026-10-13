"""Conditional mass on the existing wildcard phrase graph, not timing confidence."""
import itertools
import math


def graph(phrases, blank):
    states=[{'kind':'gap','phrase':None,'token':None,'predecessors':[]}]
    gap=0;terminals=[]
    for p,labels in enumerate(phrases):
        last_label=last_blank=None
        for j,token in enumerate(labels):
            pred=[gap] if j==0 else [last_blank]
            if last_label is not None and token!=labels[j-1]:pred.append(last_label)
            states.append({'kind':'label','phrase':p,'token':token,'predecessors':pred})
            last_label=len(states)-1
            states.append({'kind':'blank','phrase':p,'token':blank,'predecessors':[last_label]})
            last_blank=len(states)-1
        if last_label is None:raise ValueError('Empty phrase')
        terminals=[last_label,last_blank]
        states.append({'kind':'gap','phrase':None,'token':None,'predecessors':terminals})
        gap=len(states)-1
    return states,[gap,*terminals]


def logsum(values):
    import numpy as np
    return float(np.logaddexp.reduce(values))


def forward(cost, states, terminals, constraints=None):
    import numpy as np
    count=len(states);current=np.full(count,-np.inf);current[0]=0.;rows=[]
    for t,row in enumerate(cost):
        nxt=np.full(count,-np.inf)
        for j,s in enumerate(states):
            if constraints is not None and not constraints[t,j]:continue
            nxt[j]=row[j]+logsum(current[[j,*s['predecessors']]])
        rows.append(nxt);current=nxt
    return np.array(rows),logsum(current[terminals])


def distribution_summary(values):
    import numpy as np
    p=np.asarray(values,dtype=np.float64);total=float(p.sum())
    if abs(total-1)>1e-7:raise ValueError('Unnormalized conditional boundary')
    p=p/total;cdf=np.cumsum(p);frames=np.arange(len(p))
    return {'mass_sum':total,'mode_frame':int(np.argmax(p)),'mean_frame':float(p@frames),
            'q05_frame':int(np.searchsorted(cdf,.05)), 'q95_frame':int(np.searchsorted(cdf,.95)),
            'entropy_nats':float(-(p[p>0]*np.log(p[p>0])).sum()),
            'top_frames':[{'frame':int(i),'mass':float(p[i])} for i in np.argsort(-p,kind='stable')[:5]]}


def analyze(lp, phrases, intervals, blank=1024, check=lambda:None):
    import numpy as np
    states,terminals=graph(phrases,blank);T=len(lp);N=len(states)
    cost=np.zeros((T,N));maximum=lp.max(axis=1)
    for j,s in enumerate(states):
        if s['token'] is not None:cost[:,j]=lp[:,s['token']]-maximum
    alpha,z=forward(cost,states,terminals)
    if not math.isfinite(z):raise ValueError('No complete phrase graph path')
    beta=np.full((T,N),-np.inf);beta[-1,terminals]=0.
    successors=[[j for j,s in enumerate(states) if i==j or i in s['predecessors']] for i in range(N)]
    for t in range(T-2,-1,-1):
        check()
        for i,dst in enumerate(successors):beta[t,i]=logsum(cost[t+1,dst]+beta[t+1,dst])
    initial=np.full(N,-np.inf);initial[0]=0.
    zback=logsum([cost[0,j]+beta[0,j] for j in successors[0]])
    if abs(z-zback)>1e-8:raise ValueError('Forward/backward partition mismatch')
    best=initial.copy();parents=[]
    for row in cost:
        following=np.full(N,-np.inf);par=[]
        for j,s in enumerate(states):
            source=max([j,*s['predecessors']],key=lambda k:best[k])
            following[j]=best[source]+row[j];par.append(source)
        best=following;parents.append(par)
    state=max(terminals,key=lambda k:best[k]);viterbi=float(best[state]);trace=[]
    for t in range(T-1,-1,-1):trace.append(state);state=parents[t][state]
    trace.reverse()
    rows=[]
    for p,(labels,span) in enumerate(zip(phrases,intervals)):
        check();starts=np.zeros(T);ends=np.zeros(T)
        for t in range(T):
            prev=initial if t==0 else alpha[t-1]
            for j,s in enumerate(states):
                for i in s['predecessors']:
                    mass=math.exp(float(prev[i]+cost[t,j]+beta[t,j]-z))
                    if s['phrase']==p and states[i]['phrase']!=p:starts[t]+=mass
                    if t and states[i]['phrase']==p and s['phrase']!=p:ends[t-1]+=mass
        for i in terminals:
            if states[i]['phrase']==p:ends[-1]+=math.exp(float(alpha[-1,i]-z))
        which=np.array([s['phrase']==p for s in states]);occupancy=np.exp(alpha[:,which]+beta[:,which]-z).sum(axis=1)
        if np.max(occupancy)>1+1e-8:raise ValueError('Invalid occupancy')
        a,b=span['first_en_frame'],span['last_en_frame']
        mask=np.broadcast_to(~which,(T,N)).copy();mask[a:b+1,:]=which
        _,zspan=forward(cost,states,terminals,mask)
        span_mass=math.exp(zspan-z) if math.isfinite(zspan) else 0.
        rows.append({'phrase':p,'target_ids':labels,'selected_first':a,'selected_last':b,
                     'minimum_ctc_frames':len(labels)+sum(x==y for x,y in zip(labels,labels[1:])),
                     'selected_frames':b-a+1,'start_summary':distribution_summary(starts),
                     'end_summary':distribution_summary(ends),'selected_start_mass':float(starts[a]),
                     'selected_end_mass':float(ends[b]),'selected_span_conditional_mass':span_mass,
                     'expected_occupancy_frames':float(occupancy.sum()),
                     'expected_occupancy_outside_selected':float(occupancy[:a].sum()+occupancy[b+1:].sum()),
                     'start_mass':starts.tolist(),'end_mass':ends.tolist(),'occupancy':occupancy.tolist()})
    return {'conditional_log_partition':z,'backward_log_partition':zback,'partition_error':abs(z-zback),
            'viterbi_score':viterbi,'viterbi_state_trace':trace,'phrases':rows,'states':states,
            'conditional_graph_not_calibrated_confidence':True}


def ctc_sequence(lp, tokens, blank):
    """Exact standard CTC mass for one fixed token sequence on supplied frames."""
    import numpy as np
    labels=[blank]
    for t in tokens:labels.extend((t,blank))
    current=np.full(len(labels),-np.inf);current[0]=0.
    for row in lp:
        nxt=np.full_like(current,-np.inf)
        for j,token in enumerate(labels):
            sources=[j]
            if j:sources.append(j-1)
            if j>=2 and token!=blank and token!=labels[j-2]:sources.append(j-2)
            nxt[j]=logsum(current[sources])+row[token]
        current=nxt
    return logsum(current[-2:]) if tokens else float(current[0])


def greedy_ids(lp, blank):
    result=[];previous=blank
    for value in lp.argmax(axis=1):
        t=int(value)
        if t!=blank and t!=previous:result.append(t)
        previous=t
    return result


def controls():
    import numpy as np
    graph_results=[];ctc_results=[]
    for phrases,T in [([[0,1]],4),([[0,0]],4),([[0],[1]],4)]:
        weights=np.arange(1,T*3+1,dtype=float).reshape(T,3);weights/=weights.sum(axis=1,keepdims=True);lp=np.log(weights)
        states,terminals=graph(phrases,2);N=len(states);paths=[]
        def visit(prefix,prev,score):
            t=len(prefix)
            if t==T:
                if prev in terminals:paths.append((prefix,math.exp(score)))
                return
            for j,s in enumerate(states):
                if j!=prev and prev not in s['predecessors']:continue
                cost=0. if s['token'] is None else float(lp[t,s['token']]-lp[t].max())
                visit(prefix+[j],j,score+cost)
        visit([],0,0.);Z=sum(w for _,w in paths)
        spans=[]
        for p in range(len(phrases)):
            positions=[i for i,j in enumerate(paths[0][0]) if states[j]['phrase']==p]
            spans.append({'first_en_frame':min(positions),'last_en_frame':max(positions)})
        actual=analyze(lp,phrases,spans,2);error=abs(math.exp(actual['conditional_log_partition'])-Z)
        for p,span in enumerate(spans):
            start=np.zeros(T);end=np.zeros(T);spanmass=0.
            for path,w in paths:
                pos=[t for t,j in enumerate(path) if states[j]['phrase']==p];a,b=min(pos),max(pos)
                start[a]+=w/Z;end[b]+=w/Z
                if a==span['first_en_frame'] and b==span['last_en_frame']:spanmass+=w/Z
            got=actual['phrases'][p]
            error=max(error,float(abs(start-got['start_mass']).max()),float(abs(end-got['end_mass']).max()),abs(spanmass-got['selected_span_conditional_mass']))
        if error>1e-12:raise ValueError('Phrase boundary enumeration disagrees')
        graph_results.append({'phrases':phrases,'frames':T,'complete_paths':len(paths),'max_absolute_error':error})
    T=4;weights=np.arange(1,T*3+1,dtype=float).reshape(T,3);weights/=weights.sum(axis=1,keepdims=True);lp=np.log(weights)
    for target in ([],[0],[0,0],[0,1],[1,0,1]):
        mass=0.
        for raw in itertools.product(range(3),repeat=T):
            collapsed=[];last=2
            for token in raw:
                if token!=last and token!=2:collapsed.append(token)
                last=token
            if collapsed==target:mass+=math.prod(weights[t,x] for t,x in enumerate(raw))
        value=math.exp(ctc_sequence(lp,target,2));error=abs(value-mass)
        if error>1e-12:raise ValueError('Fixed-sequence CTC enumeration disagrees')
        ctc_results.append({'target':target,'raw_paths_enumerated':3**T,'absolute_error':error})
    return {'status':'success','graph_controls':graph_results,'ctc_controls':ctc_results,'human_gold':False}
