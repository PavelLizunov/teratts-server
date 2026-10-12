"""Open mixed token passing: Viterbi recombination, not transcript logsum.

Keep all English CTC/context sufficient states for four native RU histories.
Different English texts are NEVER probability-summed. The representative keeps
its literal emitted token trace and separate acoustic/context scores.
Reference principle: flashlight/text LexiconFreeDecoder.cpp (MIT).
"""
from dataclasses import dataclass
from functools import lru_cache
import math

from ctc_context import logadd
from decoder import ContextBias
from subword_pair import BOUNDARY


@dataclass(slots=True)
class PathState:
    ids: tuple
    russian: tuple
    context: tuple
    blank: bool
    acoustic: float
    credit: float

    @property
    def score(self):
        return self.acoustic+self.credit

    @property
    def key(self):
        return self.russian,self.ids[-1] if self.ids else None,self.blank,self.context


def search(events,encoded,ctc_logp,model,rules,bonus,check,same_text_logsum=False,**unused):
    import numpy as np
    graph=ContextBias(rules.paths if bonus else (),bonus)
    stats={'max_states':1,'max_english_states':0,'max_native_histories':1,
           'equivalent_state_replacements':0,'native_history_pruning_events':0}

    @lru_cache(maxsize=100000)
    def transition(context,previous_head,token):
        symbols=rules.symbols(token)
        if previous_head and previous_head!=rules.language[token] and (not symbols or symbols[0]!=BOUNDARY):
            symbols=[BOUNDARY,*symbols]
        delta=0.
        for symbol in symbols:
            value,context=graph.step(context,symbol);delta+=value
        return delta,context

    @lru_cache(maxsize=4096)
    def prediction(russian):
        if not russian:return model.predict(33,model.initial_states())
        _,s=prediction(russian[:-1]);return model.predict(russian[-1],s)

    def keep(dst,node):
        if not math.isfinite(node.score):return
        old=dst.get(node.key)
        if same_text_logsum and old is not None and old.ids==node.ids:
            dst[node.key]=PathState(old.ids,old.russian,old.context,old.blank,logadd(old.acoustic,node.acoustic),old.credit)
            return
        if old is None or node.score>old.score:
            if old is not None:stats['equivalent_state_replacements']+=1
            dst[node.key]=node

    def native_prune(states):
        ranked={}
        for node in states.values():ranked[node.russian]=max(ranked.get(node.russian,-math.inf),node.score)
        if len(ranked)>4:stats['native_history_pruning_events']+=1
        selected=set(sorted(ranked,key=ranked.get,reverse=True)[:4])
        result={k:n for k,n in states.items() if n.russian in selected}
        stats['max_native_histories']=max(stats['max_native_histories'],len(selected))
        return result

    def groups(states,ctc):
        result={}
        nodes=states.values()
        if same_text_logsum:
            by_text={}
            for node in nodes:
                old=by_text.get(node.ids)
                if old is None:by_text[node.ids]=node
                else:by_text[node.ids]=PathState(node.ids,node.russian,node.context,True,logadd(old.acoustic,node.acoustic),node.credit)
            nodes=by_text.values()
        for node in nodes:
            last=node.ids[-1] if node.ids else None
            head=rules.language[last] if last is not None else None
            if ctc and head=='rus' and last not in rules.closes:continue
            if not ctc and head=='eng' and node.russian and node.russian[-1]!=0:continue
            key=node.russian,node.context,head
            best=result.setdefault(key,[])
            # Two best distinct states suffice for excluding a nonblank repeat.
            if not best or node.score>best[0].score:best.insert(0,node)
            elif len(best)<2 or node.score>best[1].score:best.insert(1,node)
            del best[2:]
        return result

    current={PathState((),(),(),True,0.,0.).key:PathState((),(),(),True,0.,0.)}
    english=tuple(rules.heads['eng'].items());russian=tuple(rules.heads['rus'].items())
    for index,event in enumerate(events):
        check();following={}
        if event['head']=='eng':
            row=ctc_logp[event['native_frame']]
            for node in current.values():
                keep(following,PathState(node.ids,node.russian,node.context,True,node.acoustic+float(row[1024]),node.credit))
                if not node.blank and node.ids and rules.language[node.ids[-1]]=='eng':
                    keep(following,PathState(node.ids,node.russian,node.context,False,node.acoustic+float(row[node.ids[-1]]),node.credit))
            for (rids,q,head),best in groups(current,True).items():
                for token,local in english:
                    if head is None and token not in rules.starts:continue
                    before=best[0]
                    if same_text_logsum:
                        if before.ids and before.ids[-1]==token:
                            choices=[]
                            blank_node=current.get((rids,token,True,q))
                            if blank_node is not None:choices.append(blank_node)
                            if len(best)>1 and (not best[1].ids or best[1].ids[-1]!=token):choices.append(best[1])
                            if not choices:continue
                            before=max(choices,key=lambda n:n.score)
                    elif not before.blank and before.ids and before.ids[-1]==token:
                        if len(best)<2:continue
                        before=best[1]
                    delta,state=transition(q,head,token)
                    a=before.acoustic+float(row[local]);c=before.credit+delta
                    key=rids,token,False,state;old=following.get(key)
                    if old is None or a+c>old.score or (same_text_logsum and old.ids==(*before.ids,token)):
                        keep(following,PathState((*before.ids,token),rids,state,False,a,c))
            stats['max_english_states']=max(stats['max_english_states'],len(following))
        else:
            active=current
            frame=event['native_frame'];probabilities={}
            def probs(rids):
                if rids not in probabilities:
                    pred,_=prediction(rids);v=model.join(encoded[:,:,frame:frame+1],pred).astype(np.float64)
                    probabilities[rids]=v-np.logaddexp.reduce(v)
                return probabilities[rids]
            for depth in range(11):
                for node in active.values():
                    keep(following,PathState(node.ids,node.russian,node.context,node.blank,node.acoustic+float(probs(node.russian)[33]),node.credit))
                if depth==10:break
                expanded={}
                for (rids,q,head),best in groups(active,False).items():
                    before=best[0];row=probs(rids)
                    for token,local in russian:
                        delta,state=transition(q,head,token)
                        keep(expanded,PathState((*before.ids,token),(*rids,local),state,False,before.acoustic+float(row[local]),before.credit+delta))
                active=native_prune(expanded)
                if not active:break
            if index+1<len(events) and events[index+1]['head']=='eng':
                following={k:n for k,n in following.items() if rules.can_leave_head(n.ids,'rus','eng')}
            following=native_prune(following)
        if not following:raise ValueError('Empty sufficient-state search')
        stats['max_states']=max(stats['max_states'],len(following));current=following
    result={}
    final_nodes={}
    for node in current.values():
        old=final_nodes.get(node.ids)
        if old is None or (not same_text_logsum and node.score>old.score):final_nodes[node.ids]=node
        elif same_text_logsum:final_nodes[node.ids]=PathState(node.ids,node.russian,node.context,True,logadd(old.acoustic,node.acoustic),node.credit)
    for node in final_nodes.values():
        delta,state=graph.step(node.context,BOUNDARY);credit=node.credit+delta+graph.finalize(state)
        score=node.acoustic+credit
        if node.ids in result and result[node.ids]['total_score']>=score:continue
        if any(not rules.allows(node.ids[:i],t) for i,t in enumerate(node.ids)):raise ValueError('Invalid native output path')
        raw=rules.text(node.ids)
        result[node.ids]={'token_ids':list(node.ids),'raw_pieces':[rules.tokens[t] for t in node.ids],'raw_text':raw,
                          ('retained_same_text_logsum' if same_text_logsum else 'viterbi_acoustic_logp'):node.acoustic,'context_credit':credit,'total_score':score,
                          **rules.formatting_receipt(node.ids)}
    return {'hypotheses':sorted(result.values(),key=lambda h:h['total_score'],reverse=True)[:4],
            'objective':('same-token-text retained logsum, max representative across different texts; approximate forward search' if same_text_logsum else 'maximum single acoustic path plus unchanged context; NOT transcript posterior logsum'),
            'recombination':'native RU history, last emitted trained token, CTC blank state, context automaton state',
            'english_global_prefix_limit':None,'native_russian_history_beam':4,'rnnt_max_symbols':10,
            'all_trained_non_special_tokens_considered':True,'hint_paths':rules.hint_receipts if bonus else [],
            'context_score':bonus,'state_stats':stats,'prediction_cache':prediction.cache_info()._asdict()}
