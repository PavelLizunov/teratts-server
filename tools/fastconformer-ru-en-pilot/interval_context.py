"""Soft auxiliary-phrase graphs scoped to already selected native EN intervals."""
from decoder import ContextBias
from subword_pair import BOUNDARY


def settle(graph, state):
    """Virtual context boundary only: complete whole phrase or refund prefix."""
    delta, state = graph.step(state, BOUNDARY)
    return delta + graph.finalize(state)


def schedule(events, alignment, rules, bonus):
    graphs = [ContextBias((), bonus)]
    intervals = alignment['english_phrase_intervals']
    phrases = alignment['english_phrases']
    if len(intervals) != len(phrases):
        raise ValueError('Phrase/interval mismatch')
    receipts = []
    for i, (interval, tokens) in enumerate(zip(intervals, phrases)):
        if interval['phrase'] != i or not tokens or any(t not in rules.heads['eng'] for t in tokens):
            raise ValueError('Invalid trained English context phrase')
        symbols = [s for token in tokens for s in rules.symbols(token)] + [BOUNDARY]
        graphs.append(ContextBias([symbols], bonus))
        receipts.append({'graph': i + 1, 'phrase': i, 'token_ids': tokens,
                         'context_symbols': symbols, 'first_en_frame': interval['first_en_frame'],
                         'last_en_frame': interval['last_en_frame'],
                         'source': 'unaltered auxiliary alignment phrase, not human reference'})
    graph_ids = []
    for event in events:
        matches = [i + 1 for i, x in enumerate(intervals)
                   if event['head'] == 'eng' and x['first_en_frame'] <= event['native_frame'] <= x['last_en_frame']]
        if len(matches) > 1 or (event['head'] == 'eng' and not matches):
            raise ValueError('English event has ambiguous/missing interval context')
        graph_ids.append(matches[0] if matches else 0)
    return graphs, graph_ids, receipts


def controls():
    # Artificial token IDs; no audio, original transcripts or fitted word list.
    graph = ContextBias([(BOUNDARY, 11, 12, BOUNDARY)], 2.5)
    def score(g, seq):
        total, state = 0., ()
        for token in seq:
            delta, state = g.step(state, token); total += delta
        return total + settle(g, state)
    cases = {'complete_at_exit': score(graph, [BOUNDARY, 11, 12]),
             'incomplete_refunded': score(graph, [BOUNDARY, 11]),
             'wrong_word': score(graph, [BOUNDARY, 99]),
             'outside_unrewarded': score(ContextBias((), 2.5), [BOUNDARY, 11, 12]),
             'cannot_complete_across_intervals': score(graph, [BOUNDARY, 11]) + score(graph, [12]),
             'no_double_eos_payment': score(graph, [BOUNDARY, 11, 12, BOUNDARY])}
    expected = dict(complete_at_exit=10., incomplete_refunded=0., wrong_word=0.,
                    outside_unrewarded=0., cannot_complete_across_intervals=0., no_double_eos_payment=10.)
    if cases != expected:
        raise ValueError('Interval credit control mismatch')
    import numpy as np
    from state_transducer import PathState, search
    class Rules:
        paths=[]; hint_receipts=[]
        heads={'eng':{11:11,12:12},'rus':{}}
        tokens={11:'alpha',12:'beta'}; language={11:'eng',12:'eng'}
        starts={11,12}; closes=set()
        def symbols(self, token):return [BOUNDARY,token]
        def allows(self, prefix, token):return token in self.tokens
        def text(self, ids):return ' '.join(self.tokens[t] for t in ids)
        def formatting_receipt(self, ids):return {'postprocessed_text':self.text(ids)}
    rules=Rules()
    def run(lp, phrases):
        events=[{'head':'eng','native_frame':i,'center_s':i*.08} for i in range(len(lp))]
        intervals=[{'phrase':i,'first_en_frame':i,'last_en_frame':i} for i in range(len(phrases))]
        lp-=np.logaddexp.reduce(lp,axis=1,keepdims=True)
        return search(events,None,lp,None,rules,2.5,lambda:None,same_text_logsum=True,
                      interval_alignment={'english_phrases':phrases,'english_phrase_intervals':intervals})
    lp=np.full((1,1025),-100.);lp[0,11]=-30.;lp[0,12]=0.;lp[0,1024]=-8.
    rejected=run(lp,[[11]])
    if rejected['hypotheses'][0]['token_ids']!=[12] or rejected['hypotheses'][0]['context_credit']!=0.:
        raise ValueError('Soft context became a closed phrase constraint')
    lp=np.full((2,1025),-100.);lp[:,11]=0.;lp[:,1024]=0.
    timing=run(lp,[[11],[12]])
    credits={h['context_credit'] for h in timing['hypotheses'] if h['token_ids']==[11]}
    if credits!={0.,7.5}:raise ValueError('Different timing credits were merged/lost')
    a=PathState((11,),(),(),True,0.,0.,0.);b=PathState((11,),(),(),True,0.,7.5,7.5)
    if a.key==b.key:raise ValueError('Credit does not partition state keys')
    return {'status':'success','cases':cases,'synthetic_not_audio':True,
            'weak_hint_rejected':rejected['hypotheses'],'same_text_credit_partitions':timing['hypotheses'],
            'distinct_credit_keys':True,'not_full_decoder_parity':True}
