"""Diagnostic exact fixed-path mass on saved native events, never new ASR output."""
import argparse
import json
import math
from pathlib import Path
import subprocess

from ctc_context import NEG, logadd
from decoder import ContextBias
from mms_pair import digest, save


def path_mass(events, sequence):
    current = {0: (0., NEG)}
    delimiters = {4, 32}
    for index, event in enumerate(events):
        lang, row = event['head'], event['log_probs']
        old_lang = events[index-1]['head'] if index else lang
        if lang != old_lang:
            current = {length: masses for length,masses in current.items() if not length or sequence[length-1] in delimiters}
        following = {}
        def add(length, pb=NEG, pnb=NEG):
            old_b,old_nb = following.get(length,(NEG,NEG))
            following[length] = logadd(old_b,pb),logadd(old_nb,pnb)
        for length,(pb,pnb) in current.items():
            total=logadd(pb,pnb)
            add(length,pb=total+float(row[0 if lang=='eng' else 33]))
            last=sequence[length-1] if length else None
            if last is not None and ('eng' if last<32 else 'rus')==lang:
                add(length,pnb=pnb+float(row[last if lang=='eng' else last-32]))
            if length<len(sequence):
                token=sequence[length]
                if ('eng' if token<32 else 'rus')!=lang:continue
                if last in delimiters and token in delimiters:continue
                lp=float(row[token if lang=='eng' else token-32])
                add(length+1,pnb=(pb if token==last else total)+lp)
        if index+1<len(events) and events[index+1]['head']!=lang:
            following={length:masses for length,masses in following.items() if length and sequence[length-1] in delimiters}
        current=following
    return logadd(*current.get(len(sequence),(NEG,NEG)))


def credit(sequence, paths, score, last_head):
    graph=ContextBias(paths if score else (),score)
    state,total=(),0.
    for token in sequence:
        delta,state=graph.step(state,token)
        total+=delta
    if last_head=='eng':
        delta,state=graph.step(state,4)
        total+=delta
    return total+graph.finalize(state)


def main(args):
    import numpy as np
    result_path, alignment_path, ru_path, en_path, output=map(Path,(args.result,args.alignment,args.russian,args.english,args.output))
    if output.exists():raise FileExistsError('Consumed fixed-path diagnostic')
    result,alignment,ru,en=(json.loads(p.read_text()) for p in (result_path,alignment_path,ru_path,en_path))
    if digest(alignment_path)!=result['alignment_sha256'] or digest(ru_path)!=result['russian_receipt_sha256'] or digest(en_path)!=result['english_receipt_sha256']:
        raise ValueError('Changed result provenance')
    ef=en_path.with_name(en_path.stem+'-eng.npz')
    if digest(ru_path.with_suffix('.npz'))!=ru['retained_logits_sha256'] or digest(ef)!=en['heads']['eng']['retained_logits_sha256']:
        raise ValueError('Changed native arrays')
    with np.load(ru_path.with_suffix('.npz')) as f:rlp=f['log_probs'].astype(np.float64)
    with np.load(ef) as f:elp=f['log_probs'].astype(np.float64)
    vocab=en['heads']['eng']['vocab']
    elp[:,[vocab['<s>'],vocab['</s>'],vocab['<unk>']]]=-np.inf
    elp-=np.logaddexp.reduce(elp,axis=1,keepdims=True)
    arrays={'eng':elp,'rus':rlp}
    events=[{'head':e['head'],'log_probs':arrays[e['head']][e['native_frame']]} for e in alignment['selected_events']]
    proposal=[token+(0 if lang=='eng' else 32) for lang,token in alignment['label_path']]
    final_space=4 if events[-1]['head']=='eng' else 32
    paths=result['variants']['context']['context_paths']
    rows=[]
    candidates=[('auxiliary',proposal,None),('auxiliary-final-delimiter',proposal+[final_space],None)]
    candidates += [(name+'-saved-best',v['hypotheses'][0]['token_ids'],v['hypotheses'][0]) for name,v in result['variants'].items()]
    for name,sequence,saved in candidates:
        mass=path_mass(events,sequence)
        row={'candidate':name,'token_ids':sequence,'finite_complete_path':math.isfinite(mass),
             'exact_native_ctc_logsum':mass if math.isfinite(mass) else None,'scores':{}}
        if math.isfinite(mass):
            for bonus in (0.,2.5):
                value=credit(sequence,paths,bonus,events[-1]['head'])
                row['scores'][str(bonus)]={'context_credit':value,'total_score':mass+value}
        if saved:
            row['saved_beam_acoustic']=saved['routed_native_ctc_logsum']
            row['exact_minus_saved_acoustic']=mass-saved['routed_native_ctc_logsum']
        rows.append(row)
    receipt={'diagnostic_only':True,'new_transcript':False,'acoustic_rerun':False,'open_decoder_rerun':False,
             'result_sha256':digest(result_path),'alignment_sha256':digest(alignment_path),
             'source_commit':subprocess.check_output(['git','-C',str(Path(__file__).parent),'rev-parse','HEAD'],text=True).strip(),
             'candidates':rows}
    save(output,receipt)
    print(json.dumps([{k:v for k,v in row.items() if k!='token_ids'} for row in rows],ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for key in ('result','alignment','russian','english','output'):parser.add_argument('--'+key,required=True)
    main(parser.parse_args())
