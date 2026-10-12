"""One open beam with Russian CTC and English RNNT native events.

No encoder pass or text splice. English predictor persists across Russian events
and consumes only original English IDs. Auxiliary event routing remains fixed.
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
from ctc_lm import pilot
from decoder import ContextBias
from english_fc import ORIGINAL_SHA
from mms_pair import digest, save
from rnnt_fp32 import OriginalDecoder
from run import Guard
from subword_pair import BOUNDARY, RU_OFFSET, TokenRules


def search(events, encoded, ctc_logp, model, rules, bonus, check, rnnt_head='eng'):
    import numpy as np
    if rnnt_head not in ('eng','rus'):raise ValueError('Unknown trained RNNT head')
    ctc_head='rus' if rnnt_head=='eng' else 'eng'
    rnnt_blank=1024 if rnnt_head=='eng' else 33
    ctc_blank=33 if ctc_head=='rus' else 1024
    graph=ContextBias(rules.paths if bonus else (),bonus)
    @lru_cache(maxsize=100000)
    def context(prefix):
        if not prefix:return 0.,()
        score,state=context(prefix[:-1])
        for symbol in rules.symbols(prefix[-1]):
            delta,state=graph.step(state,symbol);score+=delta
        return score,state
    @lru_cache(maxsize=4096)
    def prediction(local_ids):
        if not local_ids:return model.predict(rnnt_blank,model.initial_states())
        _,state=prediction(local_ids[:-1])
        return model.predict(local_ids[-1],state)
    def rnnt_prefix(prefix):return tuple(rules.heads[rnnt_head][t] for t in prefix if t in rules.heads[rnnt_head])
    def prune(masses):
        return {p:masses[p] for p in sorted(masses,key=lambda p:logadd(*masses[p])+context(p)[0],reverse=True)[:4]}
    def add(target,prefix,pb=NEG,pnb=NEG):
        a,b=target.get(prefix,(NEG,NEG));target[prefix]=logadd(a,pb),logadd(b,pnb)
    current={(): (0.,NEG)};cap_paths=0
    for event in events:
        check();following={}
        if event['head']==ctc_head:
            row=ctc_logp[event['native_frame']]
            for prefix,(pb,pnb) in current.items():
                total=logadd(pb,pnb);add(following,prefix,pb=total+float(row[ctc_blank]))
                last=prefix[-1] if prefix else None
                for token,local in rules.heads[ctc_head].items():
                    lp=float(row[local])
                    if last==token:
                        add(following,prefix,pnb=pnb+lp)
                        if rules.allows(prefix,token):add(following,(*prefix,token),pnb=pb+lp)
                    elif rules.allows(prefix,token):add(following,(*prefix,token),pnb=total+lp)
        else:
            active=current
            for symbols in range(11):
                next_active={}
                for prefix,(pb,pnb) in active.items():
                    pred,_=prediction(rnnt_prefix(prefix))
                    logits=model.join(encoded[:,:,event['native_frame']:event['native_frame']+1],pred).astype(np.float64)
                    if rnnt_head=='eng':logits[0]=-np.inf
                    lp=logits-np.logaddexp.reduce(logits)
                    add(following,prefix,pb=pb+float(lp[rnnt_blank]),pnb=pnb+float(lp[rnnt_blank]))
                    if symbols==10:
                        cap_paths+=1;continue
                    base_credit,_=context(prefix)
                    candidates=[]
                    for token,local in rules.heads[rnnt_head].items():
                        if rules.allows(prefix,token):
                            credit,_=context((*prefix,token))
                            candidates.append((float(lp[local])+credit-base_credit,token,local))
                    # All output IDs are considered before bounded local top4.
                    for _,token,local in sorted(candidates,reverse=True)[:4]:
                        add(next_active,(*prefix,token),pnb=logadd(pb,pnb)+float(lp[local]))
                active=prune(next_active)
                if not active:break
                # Use the fixed symbol cap rather than unsafe score stopping:
                # unfinished context may still borrow additional credit.
            following=prune(following)
        current=prune(following)
        if not current:raise ValueError('Empty mixed acoustic beam')
    result=[]
    for prefix,masses in current.items():
        acoustic=logadd(*masses)
        if not math.isfinite(acoustic):continue
        credit,state=context(prefix);delta,state=graph.step(state,BOUNDARY)
        credit+=delta+graph.finalize(state)
        if any(not rules.allows(prefix[:i],t) for i,t in enumerate(prefix)):raise ValueError('Invalid mixed head word path')
        raw=rules.text(prefix)
        result.append({'token_ids':list(prefix),'raw_pieces':[rules.tokens[t] for t in prefix],
                       'raw_text':raw,'postprocessed_text':raw,'mixed_acoustic_logsum':acoustic,
                       'context_credit':credit,'total_score':acoustic+credit})
    return {'hypotheses':sorted(result,key=lambda h:h['total_score'],reverse=True)[:4],
            'beam':4,'rnnt_max_symbols':10,'paths_reaching_symbol_cap':cap_paths,
            'context_score':bonus,'hint_paths':rules.hint_receipts if bonus else [],
            'rnnt_head':rnnt_head,'ctc_head':ctc_head,('english' if rnnt_head=='eng' else 'russian')+'_predictor_persistent':True,'prediction_cache':prediction.cache_info()._asdict()}


def cell(args, alignment_fn=None):
    import numpy as np
    import sentencepiece as spm
    root,em,parent,alignment_path,output=Path(args.root),Path(args.model),Path(args.receipt),Path(args.context_receipt),Path(args.output)
    if output.exists():raise FileExistsError('Consumed mixed decoder cell')
    start=time.monotonic();guard=Guard(600,4096)
    result={'status':'failed','variants':{},'audio_or_encoder_rerun':False,'per_region_decoders':False,
            'postprocessing':'none','source_commit':subprocess.check_output(['git','-C',str(Path(__file__).parent),'rev-parse','HEAD'],text=True).strip()}
    try:
        en=json.loads(parent.read_text());alignment=json.loads(alignment_path.read_text())
        clip=parent.stem.removesuffix('-encoder')
        rp=root/'alternative-methods/results-giga-component-v1'/(clip+'.json');ru=json.loads(rp.read_text())
        if ru['audio_sha256']!=en['audio_sha256'] or en['audio_sha256']!=alignment['audio_sha256']:raise ValueError('Mixed audio provenance')
        if digest(parent.with_suffix('.npz'))!=en['retained_encoder_sha256'] or digest(rp.with_suffix('.npz'))!=ru['retained_logits_sha256']:raise ValueError('Changed acoustic arrays')
        with np.load(parent.with_suffix('.npz')) as file:encoded=file['encoded']
        with np.load(rp.with_suffix('.npz')) as file:rlp=file['log_probs'].astype(np.float64)
        model=OriginalDecoder(em/'original.nemo',expected_sha=ORIGINAL_SHA,classes=1025)
        prepared=json.loads((em/'prepared.json').read_text())
        if digest(em/'tokenizer.model')!=prepared['tokenizer_sha256']:raise ValueError('Changed original English tokenizer')
        rm=root/'alternative-methods/giga-v3-ctc';assets=json.loads((rm/'download-receipt.json').read_text())
        if digest(rm/'download-receipt.json')!=ru['asset_receipt_sha256'] or digest(rm/'tokens.txt')!=next(x['sha256'] for x in assets['files'] if x['name']=='tokens.txt'):raise ValueError('Changed Russian vocabulary')
        tokens={int(s.rsplit(' ',1)[1]):s.rsplit(' ',1)[0] for s in (rm/'tokens.txt').read_text().splitlines()}
        rules=TokenRules({int(i):p for i,p in prepared['vocab'].items()},tokens,spm.SentencePieceProcessor(model_file=str(em/'tokenizer.model')))
        result.update(audio_sha256=en['audio_sha256'],encoder_receipt_sha256=digest(parent),alignment_sha256=digest(alignment_path),
                      russian_receipt_sha256=digest(rp),tensor_hashes=model.tensor_hashes,
                      head_offsets={'eng':0,'rus':RU_OFFSET},load_s=time.monotonic()-start)
        if alignment_fn is not None:
            before=time.monotonic()
            updated=alignment_fn(alignment,encoded,rlp,model,guard.check)
            updated.update(audio_sha256=en['audio_sha256'],parent_alignment_sha256=digest(alignment_path),
                           encoder_receipt_sha256=digest(parent),russian_receipt_sha256=digest(rp))
            new_path=output.with_name(output.stem+'-alignment.json');save(new_path,updated)
            alignment=updated;result.update(alignment_sha256=digest(new_path),alignment_s=time.monotonic()-before)
        for name,bonus in (('no-context',0.),('context',1.5)):
            before=time.monotonic();value=search(alignment['selected_events'],encoded,rlp,model,rules,bonus,guard.check)
            value['decode_s']=time.monotonic()-before
            if not value['hypotheses']:raise ValueError('No finite mixed output')
            save(output.with_name(output.stem+'-'+name+'.json'),value);result['variants'][name]=value
            print(name,value['hypotheses'][0]['raw_text'],flush=True)
        result['status']='success'
    except Exception as error:result['error']=type(error).__name__+': '+str(error);raise
    finally:
        result.update(elapsed_s=time.monotonic()-start,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,guard=guard.receipt());save(output,result)


if __name__=='__main__':
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='mode',required=True);c=s.add_parser('cell')
    for key in ('root','model','receipt','context-receipt','output'):c.add_argument('--'+key,required=True)
    q=s.add_parser('pilot');q.add_argument('manifest');args=p.parse_args()
    if args.mode=='cell':cell(args)
    else:pilot(args,cell_script=__file__)
