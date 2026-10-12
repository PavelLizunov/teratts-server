"""Frozen probability-only LM inside retained Parakeet/GigaAM open CTC beam."""
import argparse
import json
from pathlib import Path
import resource
import subprocess
import time

from ctc_lm import LanguageScorer, PARAMETERS, pilot
from mms_pair import digest, save
from run import Guard
from subword_pair import TokenRules, decode


def cell(args):
    import numpy as np
    import sentencepiece as spm
    root,parent,output=Path(args.root),Path(args.receipt),Path(args.output)
    if output.exists():raise FileExistsError('Consumed subword LM cell')
    start=time.monotonic();guard=Guard(600,4096);scorer=None
    result={'status':'failed','audio_or_encoder_rerun':False,'routing_rerun':False,'language_model_generates_text':False,
            'postprocessing':'none','variants':{},'parameters':PARAMETERS,
            'source_commit':subprocess.check_output(['git','-C',str(Path(__file__).parent),'rev-parse','HEAD'],text=True).strip()}
    try:
        previous=json.loads(parent.read_text());ap=Path(args.context_receipt);alignment=json.loads(ap.read_text())
        if digest(ap)!=previous['alignment_sha256']:raise ValueError('Changed phrase routing')
        clip=parent.name.split('-')[1]
        rp=root/'alternative-methods/results-giga-component-v1'/(clip+'.json');ep=root/'alternative-methods/results-parakeet-english-v1'/(clip+'.json')
        ru,en=(json.loads(p.read_text()) for p in (rp,ep))
        if digest(rp)!=previous['russian_receipt_sha256'] or digest(ep)!=previous['english_receipt_sha256']:raise ValueError('Changed component provenance')
        for path,receipt in ((rp,ru),(ep,en)):
            if digest(path.with_suffix('.npz'))!=receipt['retained_logits_sha256']:raise ValueError('Changed retained score array')
        em=root/'alternative-methods/parakeet-english-ctc';prepared=json.loads((em/'prepared.json').read_text())
        if digest(em/'prepared.json')!=en['prepared_sha256'] or digest(em/'tokenizer.model')!=prepared['tokenizer_sha256']:raise ValueError('Changed trained English map')
        rm=root/'alternative-methods/giga-v3-ctc';assets=json.loads((rm/'download-receipt.json').read_text())
        if digest(rm/'download-receipt.json')!=ru['asset_receipt_sha256'] or digest(rm/'tokens.txt')!=next(x['sha256'] for x in assets['files'] if x['name']=='tokens.txt'):raise ValueError('Changed Russian trained map')
        ru_tokens={int(s.rsplit(' ',1)[1]):s.rsplit(' ',1)[0] for s in (rm/'tokens.txt').read_text().splitlines()}
        rules=TokenRules({int(i):p for i,p in prepared['vocab'].items()},ru_tokens,spm.SentencePieceProcessor(model_file=str(em/'tokenizer.model')),prepared['english_case'])
        with np.load(rp.with_suffix('.npz')) as f:rlp=f['log_probs'].astype(np.float64)
        with np.load(ep.with_suffix('.npz')) as f:elp=f['log_probs'].astype(np.float64)
        elp[:,0]=-np.inf;elp-=np.logaddexp.reduce(elp,axis=1,keepdims=True)
        arrays={'eng':elp,'rus':rlp};events=[{**e,'log_probs':arrays[e['head']][e['native_frame']]} for e in alignment['selected_events']]
        scorer=LanguageScorer(Path(args.model),rules.tokens,guard.check)
        result.update(audio_sha256=previous['audio_sha256'],parent_receipt_sha256=digest(parent),alignment_sha256=digest(ap),lm_loading=scorer.load_receipt,load_s=time.monotonic()-start)
        before=time.monotonic();value=decode(events,rules,2.5,guard.check,prefix_scorer=scorer)
        if not value['hypotheses']:raise ValueError('No finite trained-head LM path')
        value['decode_s']=time.monotonic()-before;value['best_score_consistency']=scorer.observe_best_score(tuple(value['hypotheses'][0]['token_ids']))
        save(output.with_name(output.stem+'-context.json'),value);result['variants']['context']=value;result['status']='success'
        print(value['hypotheses'][0]['raw_text'],flush=True)
    except Exception as error:result['error']=type(error).__name__+': '+str(error);raise
    finally:
        if scorer:result['lm_runtime']={'forward_calls':scorer.forward_calls,'scored_sequences':scorer.scored_sequences,'processed_suffix_tokens':scorer.processed_suffix_tokens,'peak_cache_bytes':scorer.peak_cache_bytes}
        result.update(elapsed_s=time.monotonic()-start,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,guard=guard.receipt());save(output,result)


if __name__=='__main__':
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='mode',required=True);c=sub.add_parser('cell')
    for key in ('root','model','receipt','context-receipt','output'):c.add_argument('--'+key,required=True)
    p=sub.add_parser('pilot');p.add_argument('manifest');args=parser.parse_args()
    if args.mode=='cell':cell(args)
    else:pilot(args,cell_script=__file__)
