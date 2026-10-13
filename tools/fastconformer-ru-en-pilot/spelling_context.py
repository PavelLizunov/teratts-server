"""Single-phrase spelling context with exact original completion-credit budget."""
from ctc_occurrence import BOUNDARY as TEXT_BOUNDARY, pattern_for, symbols
from decoder import ContextBias
from subword_pair import BOUNDARY


def character_symbols(text):
    return [BOUNDARY if c==TEXT_BOUNDARY else ord(c) for c in symbols(text)]


class SpellingContext(ContextBias):
    def __init__(self, text=None, original_units=0, score=2.5):
        if score!=2.5:raise ValueError('Spelling mode requires exact frozen score2.5')
        path=[] if text is None else [BOUNDARY if c==TEXT_BOUNDARY else ord(c) for c in pattern_for(text)]
        super().__init__([path] if path else [],score)
        if not path:self.weights=();return
        inside=len(path)-2;units=original_units-2
        if inside<1 or units<1:raise ValueError('Invalid spelling credit budget')
        self.weights=(1,*(k*units//inside-(k-1)*units//inside for k in range(1,inside+1)),1)
        if sum(self.weights)!=original_units:raise ValueError('Completion budget changed')

    def pending_units(self,state):
        ids=tuple(t for t,covered in state)
        n=max((len(p) for p in self.prefixes if len(p)<=len(ids) and ids[-len(p):]==p),default=0)
        return sum(w for (_,covered),w in zip(state[-n:],self.weights[:n]) if not covered) if n else 0

    def step(self,state,token):
        if not self.paths:return 0.,()
        # Word separators form one context boundary, never an acoustic rewrite.
        if token==BOUNDARY and state and state[-1][0]==BOUNDARY:return 0.,state
        pending=self.pending_units(state);sequence=(*state,(int(token),False));ids=tuple(t for t,c in sequence)
        complete=len(self.paths[0]) if len(ids)>=len(self.paths[0]) and ids[-len(self.paths[0]):]==self.paths[0] else 0
        paid=0
        if complete:
            paid=sum(w for (_,covered),w in zip(sequence[-complete:],self.weights) if not covered)
            sequence=(*sequence[:-complete],*((t,True) for t,c in sequence[-complete:]))
        following=self.pending_units(sequence)
        retained=max((len(p) for p in self.prefixes if len(p)<=len(ids) and ids[-len(p):]==p),default=0)
        return self.score*(paid+following-pending),sequence[-retained:] if retained else ()

    def token_step(self,state,previous_head,token,rules):
        chars=character_symbols(rules.tokens[token])
        if previous_head and previous_head!=rules.language[token] and (not chars or chars[0]!=BOUNDARY):chars=[BOUNDARY,*chars]
        credit=0.
        for c in chars:
            delta,state=self.step(state,c);credit+=delta
        return credit,state


def completion(graph, chunks):
    from interval_context import settle
    credit=0.;state=();prefixes=[]
    for chunk in chunks:
        for c in character_symbols(chunk):
            d,state=graph.step(state,c);credit+=d
        prefixes.append((credit,state))
    return credit+settle(graph,state),prefixes


def controls():
    import itertools
    import numpy as np
    from state_transducer import search
    graph=SpellingContext('alpha',4)
    reference=completion(graph,list(' alpha'))[1];chunkings=0
    text=' alpha'
    for cuts in itertools.product((False,True),repeat=len(text)-1):
        chunks=[];last=0;ends=[]
        for i,cut in enumerate(cuts,1):
            if cut:chunks.append(text[last:i]);ends.append(i);last=i
        chunks.append(text[last:]);ends.append(len(text))
        final,prefixes=completion(graph,chunks)
        if final!=10. or any(got!=reference[end-1] for got,end in zip(prefixes,ends)):raise ValueError('Token chunking affects spelling state/credit')
        chunkings+=1
    cases={s:completion(graph,[s])[0] for s in (' alpha',' al',' beta',' xalpha',' alphax',' (alpha!)',' alpha alpha',' alpha alpha alpha',' alpha ')}
    expected={' alpha':10.,' al':0.,' beta':0.,' xalpha':0.,' alphax':0.,' (alpha!)':10.,' alpha alpha':17.5,' alpha alpha alpha':25.,' alpha ':10.}
    if cases!=expected:raise ValueError('Spelling whole-word/refund/overlap control mismatch')
    if completion(graph,[' al'])[0]+completion(graph,['pha'])[0]!=0.:raise ValueError('Context leaks across intervals')
    if completion(SpellingContext(),[' alpha'])[0]!=0.:raise ValueError('Context outside interval rewarded')
    class Rules:
        paths=[];hint_receipts=[];heads={'eng':{11:11,12:12},'rus':{}}
        tokens={11:'▁alpha',12:'▁beta'};language={11:'eng',12:'eng'};starts={11,12};closes=set()
        def symbols(self,t):return [BOUNDARY,t]
        def allows(self,p,t):return t in self.tokens
        def text(self,ids):return ''.join(self.tokens[t] for t in ids).replace('▁',' ').strip()
        def formatting_receipt(self,ids):return {'postprocessed_text':self.text(ids)}
    lp=np.full((1,1025),-100.);lp[0,11]=-30.;lp[0,12]=0.;lp[0,1024]=-8.;lp-=np.logaddexp.reduce(lp,axis=1,keepdims=True)
    result=search([{'head':'eng','native_frame':0,'center_s':0.}],None,lp,None,Rules(),2.5,lambda:None,
                  same_text_logsum=True,interval_alignment={'english_phrases':[[11]],'english_phrase_intervals':[{'phrase':0,'first_en_frame':0,'last_en_frame':0}]},spelling_context=True)
    if result['hypotheses'][0]['token_ids']!=[12] or result['hypotheses'][0]['context_credit']!=0.:raise ValueError('Soft spelling hint forced output')
    return {'status':'success','all_chunkings':chunkings,'every_common_prefix_equal':True,'cases':cases,
            'outside_and_cross_interval_zero':True,'weak_hint_rejected':True,'synthetic_not_speech_gold':True}
