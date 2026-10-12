"""Exact saved-path mixed CTC/RNNT mass and zero-encoder internal-LM proxy.

Diagnostic only: no open decoding, new transcript, encoder or waveform pass.
"""
import argparse
from functools import lru_cache
import json
import math
from pathlib import Path
import resource
import subprocess
import time

from ctc_context import NEG, logadd
from decoder import ContextBias
from english_fc import ORIGINAL_SHA
from mms_pair import digest, save
from rnnt_fp32 import OriginalDecoder
from run import Guard
from subword_pair import BOUNDARY, RU_OFFSET, TokenRules


def context_credit(sequence,rules,bonus):
    graph=ContextBias(rules.paths if bonus else (),bonus);state,total=(),0.
    for token in sequence:
        for symbol in rules.symbols(token):
            delta,state=graph.step(state,symbol);total+=delta
    delta,state=graph.step(state,BOUNDARY)
    return total+delta+graph.finalize(state)


def path_scores(events,sequence,rules,ru_logp,encoded,model,check):
    import numpy as np
    if any(not rules.allows(sequence[:i],t) for i,t in enumerate(sequence)):raise ValueError('Invalid fixed path')
    n=len(sequence);english=[()]
    for token in sequence:english.append(english[-1]+((token,) if token<RU_OFFSET else ()))
    @lru_cache(maxsize=None)
    def prediction(prefix):
        if not prefix:return model.predict(1024,model.initial_states())
        _,state=prediction(prefix[:-1]);return model.predict(prefix[-1],state)
    @lru_cache(maxsize=None)
    def probabilities(frame,prefix):
        pred,_=prediction(prefix)
        logits=model.join(encoded[:,:,frame:frame+1],pred).astype(np.float64)
        logits[0]=-np.inf
        return logits-np.logaddexp.reduce(logits)
    def mass(cap):
        current={0:(0.,NEG)}
        def add(target,u,pb=NEG,pnb=NEG):
            a,b=target.get(u,(NEG,NEG));target[u]=logadd(a,pb),logadd(b,pnb)
        for event in events:
            check();following={};frame=event['native_frame']
            if event['head']=='rus':
                row=ru_logp[frame]
                for u,(pb,pnb) in current.items():
                    total=logadd(pb,pnb);add(following,u,pb=total+float(row[33]))
                    last=sequence[u-1] if u else None
                    if last is not None and last>=RU_OFFSET:add(following,u,pnb=pnb+float(row[last-RU_OFFSET]))
                    if u<n and sequence[u]>=RU_OFFSET:
                        token=sequence[u];add(following,u+1,pnb=(pb if token==last else total)+float(row[token-RU_OFFSET]))
            else:
                active=current
                for depth in range((n if cap is None else cap)+1):
                    after={}
                    for u,(pb,pnb) in active.items():
                        if not math.isfinite(logadd(pb,pnb)):continue
                        lp=probabilities(frame,english[u]);add(following,u,pb=pb+float(lp[1024]),pnb=pnb+float(lp[1024]))
                        if (cap is None or depth<cap) and u<n and sequence[u]<RU_OFFSET:
                            add(after,u+1,pnb=logadd(pb,pnb)+float(lp[sequence[u]]))
                    active=after
                    if not active:break
            current=following
        return logadd(*current.get(n,(NEG,NEG)))
    capped=mass(10);uncapped=mass(None)
    ilm=0.;ilm_tokens=[];prefix=()
    for token in sequence:
        if token>=RU_OFFSET:continue
        pred,_=prediction(prefix);logits=model.join(np.zeros((1,512,1),np.float32),pred).astype(np.float64)
        score=float(logits[token]-np.logaddexp.reduce(logits[1:1024]))
        ilm+=score;ilm_tokens.append({'token_id':token,'piece':rules.tokens[token],'log_probability':score});prefix+=token,
    return {'capped10_mass':capped if math.isfinite(capped) else None,'uncapped_mass':uncapped if math.isfinite(uncapped) else None,
            'cap_mass_loss':uncapped-capped if math.isfinite(capped) else None,'english_internal_lm_proxy':ilm,
            'english_proxy_tokens':ilm_tokens,'finite_complete_path':math.isfinite(uncapped)}


def main(args):
    import numpy as np
    import sentencepiece as spm
    root,output=Path(args.root),Path(args.output)
    if output.exists():raise FileExistsError('Consumed mixed path diagnostic')
    start=time.monotonic();guard=Guard(600,4096)
    result={'status':'failed','diagnostic_only':True,'new_transcript':False,'open_decoder_rerun':False,'acoustic_rerun':False,
            'source_commit':subprocess.check_output(['git','-C',str(Path(__file__).parent),'rev-parse','HEAD'],text=True).strip(),
            'zero_encoder_proxy_is_approximation':True,'english_proxy_normalized_over_ids':[1,1023],'candidates':[]}
    try:
        rp=root/'results-mixed-transducer-v1'/(args.clip+'.json');receipt=json.loads(rp.read_text())
        ap=root/f'round8-{args.clip}-subword-pair-alignment.json';alignment=json.loads(ap.read_text())
        ep=root/'results-english-rnnt-v1'/(args.clip+'-encoder.json');en=json.loads(ep.read_text())
        gp=root/'results-giga-component-v1'/(args.clip+'.json');ru=json.loads(gp.read_text())
        for path,key in ((ap,'alignment_sha256'),(ep,'encoder_receipt_sha256'),(gp,'russian_receipt_sha256')):
            if digest(path)!=receipt[key]:raise ValueError('Changed source receipt')
        if digest(ep.with_suffix('.npz'))!=en['retained_encoder_sha256'] or digest(gp.with_suffix('.npz'))!=ru['retained_logits_sha256']:raise ValueError('Changed model outputs')
        with np.load(ep.with_suffix('.npz')) as file:encoded=file['encoded']
        with np.load(gp.with_suffix('.npz')) as file:rlp=file['log_probs'].astype(np.float64)
        em=root/'english-fastconformer';prepared=json.loads((em/'prepared.json').read_text())
        if digest(em/'tokenizer.model')!=prepared['tokenizer_sha256']:raise ValueError('Changed tokenizer')
        rm=root/'giga-v3-ctc';assets=json.loads((rm/'download-receipt.json').read_text())
        if digest(rm/'download-receipt.json')!=ru['asset_receipt_sha256'] or digest(rm/'tokens.txt')!=next(x['sha256'] for x in assets['files'] if x['name']=='tokens.txt'):raise ValueError('Changed Russian map')
        tokens={int(s.rsplit(' ',1)[1]):s.rsplit(' ',1)[0] for s in (rm/'tokens.txt').read_text().splitlines()}
        rules=TokenRules({int(i):p for i,p in prepared['vocab'].items()},tokens,spm.SentencePieceProcessor(model_file=str(em/'tokenizer.model')))
        model=OriginalDecoder(em/'original.nemo',expected_sha=ORIGINAL_SHA,classes=1025)
        candidates=[('auxiliary',[t+(RU_OFFSET if lang=='rus' else 0) for lang,t in alignment['label_path']],None)]
        candidates.extend((name+'-saved-best',v['hypotheses'][0]['token_ids'],v['hypotheses'][0]) for name,v in receipt['variants'].items())
        for name,sequence,saved in candidates:
            row={'candidate':name,'token_ids':sequence,**path_scores(alignment['selected_events'],sequence,rules,rlp,encoded,model,guard.check)}
            row['context_credit']=context_credit(sequence,rules,1.5)
            if row['finite_complete_path']:row['context_total']=row['uncapped_mass']+row['context_credit']
            if saved:
                row['saved_beam_acoustic']=saved['mixed_acoustic_logsum']
                if row['capped10_mass'] is not None:row['exact_minus_beam']=row['capped10_mass']-saved['mixed_acoustic_logsum']
            result['candidates'].append(row);print(json.dumps({k:v for k,v in row.items() if k not in ('token_ids','english_proxy_tokens')},ensure_ascii=False),flush=True)
        aux=result['candidates'][0]
        for row in result['candidates'][1:]:
            if aux['finite_complete_path'] and row['finite_complete_path']:
                gap=row['context_total']-aux['context_total'];prior_difference=row['english_internal_lm_proxy']-aux['english_internal_lm_proxy']
                row['auxiliary_context_score_deficit']=gap;row['proxy_difference_error_minus_aux']=prior_difference
                row['proxy_subtraction_coefficient_for_pairwise_tie']=gap/prior_difference if prior_difference>0 else None
        result.update(status='success',result_sha256=digest(rp),audio_sha256=receipt['audio_sha256'])
    except Exception as error:result['error']=type(error).__name__+': '+str(error);raise
    finally:
        result.update(elapsed_s=time.monotonic()-start,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,guard=guard.receipt());save(output,result)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for key in ('root','clip','output'):parser.add_argument('--'+key,required=True)
    main(parser.parse_args())
