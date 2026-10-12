"""New Russian RNNT and retained English CTC in a single open native-clock beam."""
import argparse
import json
from pathlib import Path
import resource
import subprocess
import time

from ctc_lm import pilot
from giga_transducer import Model
from mixed_transducer import search
from mms_pair import digest, save
from run import Guard
from subword_pair import TokenRules, RU_OFFSET


def cell(args, rules_type=TokenRules, english_model='parakeet-english-ctc', english_results='results-parakeet-english-v1'):
    import numpy as np
    import sentencepiece as spm
    root,rm,rp,ap,output=map(Path,(args.root,args.model,args.receipt,args.context_receipt,args.output))
    if output.exists():raise FileExistsError('Consumed reverse mixed acoustic cell')
    start=time.monotonic();guard=Guard(600,4096)
    result={'status':'failed','variants':{},'audio_or_encoder_rerun':False,'routing_rerun':False,'per_region_decoders':False,'postprocessing':'none',
            'proposal_text_used_by_final_decoder':False,'source_commit':subprocess.check_output(['git','-C',str(Path(__file__).parent),'rev-parse','HEAD'],text=True).strip()}
    try:
        ru=json.loads(rp.read_text());alignment=json.loads(ap.read_text());clip=rp.stem
        ep=root/'alternative-methods'/english_results/(clip+'.json');en=json.loads(ep.read_text())
        parent=ap.with_name(ap.name.replace('-alignment.json','.json'));prior=json.loads(parent.read_text())
        fp=root/'alternative-methods/results-parakeet-english-v1'/(clip+'.json')
        route_english=ep if prior.get('routing_english_receipt_sha256')==digest(ep) else fp
        if digest(ap)!=prior['alignment_sha256'] or digest(route_english)!=prior['english_receipt_sha256']:raise ValueError('Changed frozen English routing provenance')
        if english_results!='results-parakeet-english-v1':
            parent_en=json.loads(fp.read_text())
            if en['audio_sha256']!=parent_en['audio_sha256'] or en['native_output_frames']!=parent_en['native_output_frames']:raise ValueError('Changed compact English clock/audio')
        if len({ru['audio_sha256'],en['audio_sha256'],alignment['audio_sha256']})!=1:raise ValueError('Different recordings')
        if digest(rp.with_suffix('.npz'))!=ru['retained_encoder_sha256'] or digest(ep.with_suffix('.npz'))!=en['retained_logits_sha256']:raise ValueError('Changed native arrays')
        if digest(rm/'prepared.json')!=ru['prepared_sha256']:raise ValueError('Changed Russian transducer provenance')
        em=root/'alternative-methods'/english_model;prepared=json.loads((em/'prepared.json').read_text())
        if english_results!='results-parakeet-english-v1' and prepared['fp32_parent_prepared_sha256']!=parent_en['prepared_sha256']:raise ValueError('Compact export belongs to a different verified parent')
        if digest(em/'prepared.json')!=en['prepared_sha256'] or digest(em/'tokenizer.model')!=prepared['tokenizer_sha256']:raise ValueError('Changed English trained vocabulary')
        with np.load(rp.with_suffix('.npz')) as file:encoded=file['encoded']
        with np.load(ep.with_suffix('.npz')) as file:elp=file['log_probs'].astype(np.float64)
        elp[:,0]=-np.inf;elp-=np.logaddexp.reduce(elp,axis=1,keepdims=True)
        model=Model(rm);rules=rules_type({int(k):v for k,v in prepared['vocab'].items()},{int(k):v for k,v in model.prepared['tokens'].items()},spm.SentencePieceProcessor(model_file=str(em/'tokenizer.model')),prepared['english_case'])
        result['postprocessing']=getattr(rules,'formatting','none')
        for event in alignment['selected_events']:
            head,index=event['head'],event['native_frame'];center=index*(.04 if head=='rus' else .08)+(model.prepared['nominal_origin_s'] if head=='rus' else 0.)
            if abs(center-event['center_s'])>1e-9 or not 0<=index<(encoded.shape[-1] if head=='rus' else len(elp)):raise ValueError('Changed native event clock')
        result.update(audio_sha256=ru['audio_sha256'],russian_receipt_sha256=digest(rp),english_receipt_sha256=digest(ep),alignment_sha256=digest(ap),
                      trained_head_offsets={'eng':0,'rus':RU_OFFSET},russian_prepared_sha256=digest(rm/'prepared.json'),load_s=time.monotonic()-start)
        for name,bonus in (('no-context',0.),('context',2.5)):
            before=time.monotonic();value=search(alignment['selected_events'],encoded,elp,model,rules,bonus,guard.check,rnnt_head='rus');value['decode_s']=time.monotonic()-before
            if not value['hypotheses']:raise ValueError('No finite mixed Russian RNNT path')
            save(output.with_name(output.stem+'-'+name+'.json'),value);result['variants'][name]=value
            print(name,value['hypotheses'][0]['raw_text'],flush=True)
        result['status']='success'
    except Exception as error:result['error']=type(error).__name__+': '+str(error);raise
    finally:
        result.update(elapsed_s=time.monotonic()-start,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,guard=guard.receipt());save(output,result)


if __name__=='__main__':
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='mode',required=True);c=sub.add_parser('cell')
    for key in ('root','model','receipt','context-receipt','output'):c.add_argument('--'+key,required=True)
    p=sub.add_parser('pilot');p.add_argument('manifest');args=parser.parse_args()
    if args.mode=='cell':cell(args)
    else:pilot(args,cell_script=__file__)
