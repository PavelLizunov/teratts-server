"""A matching route alone cannot prove reusable output from a different head."""


def array_identity(receipt):
    if 'retained_array_sha256' in receipt:return 'values',receipt['retained_array_sha256']
    if 'retained_logits_sha256' in receipt:return 'log_probs',receipt['retained_logits_sha256']
    raise ValueError('Receipt does not identify a retained acoustic array')


def reuse_identity(prior, current_hashes, events, context_mode):
    previous=prior.get('source_hashes',{})
    if not current_hashes.get('rus') or previous.get('rus')!=current_hashes['rus']:return None
    if any(e['head']=='eng' for e in events):
        return 'identical_english_and_russian_receipts' if current_hashes.get('eng') and previous.get('eng')==current_hashes['eng'] else None
    # Both callers also require exact events, score, mode and graph retention.
    search=prior.get('search',{})
    if context_mode!='global-fixed' or search.get('context_mode','global-fixed')!='global-fixed':return None
    hypotheses=search.get('hypotheses',[]);hints=search.get('hint_paths',[])
    if not hypotheses:return None
    if any(h.get('context_credit')!=0. or any(not 1025<=t<1058 for t in h['token_ids']) for h in hypotheses):return None
    if any(not h.get('token_ids') or any(not 0<t<1024 for t in h['token_ids']) for h in hints):return None
    return 'all_russian_same_receipt_zero_credit_english_only_context'


def controls():
    import copy
    en=[{'head':'eng'}];ru=[{'head':'rus'}];hashes={'eng':'newE','rus':'R'}
    prior={'source_hashes':{'eng':'oldE','rus':'R'},'search':{'context_mode':'global-fixed',
           'hypotheses':[{'token_ids':[1026,1025],'context_credit':0.}],
           'hint_paths':[{'token_ids':[41,287]}]}}
    cases={'changed_english_rejected':reuse_identity(prior,hashes,en,'global-fixed') is None,
           'all_russian_proved':reuse_identity(prior,hashes,ru,'global-fixed') is not None,
           'scoped_no_cross_head_reuse':reuse_identity(prior,hashes,ru,'auxiliary-interval-v1') is None}
    equal=copy.deepcopy(prior);equal['source_hashes']['eng']='newE'
    cases['same_heads_accepted']=reuse_identity(equal,hashes,en,'global-fixed') is not None
    bad=copy.deepcopy(prior);bad['source_hashes']['rus']='otherR'
    cases['changed_russian_rejected']=reuse_identity(bad,hashes,ru,'global-fixed') is None
    bad=copy.deepcopy(prior);bad.pop('source_hashes')
    cases['missing_identity_rejected']=reuse_identity(bad,hashes,en,'global-fixed') is None
    bad=copy.deepcopy(prior);bad['search']['hypotheses'][0]['token_ids']=[41]
    cases['english_output_on_russian_route_rejected']=reuse_identity(bad,hashes,ru,'global-fixed') is None
    bad=copy.deepcopy(prior);bad['search']['hypotheses'][0]['context_credit']=2.5
    cases['nonzero_credit_russian_rejected']=reuse_identity(bad,hashes,ru,'global-fixed') is None
    bad=copy.deepcopy(prior);bad['search']['hint_paths'][0]['token_ids']=[1025]
    cases['russian_hint_cross_head_reuse_rejected']=reuse_identity(bad,hashes,ru,'global-fixed') is None
    if not all(cases.values()):raise ValueError('Acoustic cache proof control failed')
    if array_identity({'retained_array_sha256':'x'})!=('values','x') or array_identity({'retained_logits_sha256':'y'})!=('log_probs','y'):raise ValueError('Array schema identity failed')
    return {'status':'success','cases':cases,'array_schema_controls':2,'not_asr_quality':True}
