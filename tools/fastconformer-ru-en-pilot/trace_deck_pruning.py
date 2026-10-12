"""Observe pruning only; callback never alters scores or candidates."""
import argparse
import json
from pathlib import Path
from ctc_context import logadd
from deck_path_mass import Model,NativeWordRules,Guard,save,digest
from mixed_transducer import search


def main(args):
    import numpy as np
    import sentencepiece as spm
    cfg=json.loads(Path(args.manifest).read_text());base=Path(cfg['retained_inputs_directory']);em=Path(cfg['english_model']);p=json.loads((em/'prepared.json').read_text());model=Model(Path(cfg['russian_model']));guard=Guard(600,1280)
    with np.load(base/'long-eng.npz') as f:lp=f['values'].astype(np.float64)
    with np.load(base/'long-rus.npz') as f:encoded=f['values']
    lp[:,0]=-np.inf;lp-=np.logaddexp.reduce(lp,axis=1,keepdims=True)
    a=json.loads((base/'long-alignment.json').read_text());rules=NativeWordRules({int(k):v for k,v in p['vocab'].items()},{int(k):v for k,v in model.prepared['tokens'].items()},spm.SentencePieceProcessor(model_file=str(em/'tokenizer.model')),p['english_case'])
    rows=json.loads(Path(args.paths).read_text());target=tuple(rows[0]['token_ids']);last_by_event={};calls=[]
    def observe(index,event,ranked,masses,context,width):
        compatible=[(i,p) for i,p in enumerate(ranked) if tuple(p)==target[:len(p)]]
        hit=compatible[0] if compatible else None
        def h(p):return {'ids':list(p),'text':rules.text(p),'score':logadd(*masses[p])+context(p)[0],'context':context(p)[0]}
        r={'index':index,'event':event,'width':width,'candidates':len(ranked),'compatible_rank':hit[0]+1 if hit else None,'compatible':h(hit[1]) if hit else None,'best':h(ranked[0]) if ranked else None}
        calls.append(r);last_by_event[index]=r
    result=search(a['selected_events'],encoded,lp,model,rules,2.5,guard.check,rnnt_head='rus',ctc_beam=32,observe_pruning=observe)
    expected=rows[1]['token_ids']
    if result['hypotheses'][0]['token_ids']!=expected:raise ValueError('Observer altered known result or runtime differs')
    loss=next((i for i,r in sorted(last_by_event.items()) if r['compatible_rank'] is None or r['compatible_rank']>r['width']),None)
    nearby=[r for r in calls if loss is not None and loss-2<=r['index']<=loss+1]
    receipt={'same_winning_path':True,'first_outer_loss_event':loss,'nearby_pruning':nearby,'input_paths_sha256':digest(args.paths)}
    save(Path(args.output),receipt)
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for key in ('manifest','paths','output'):p.add_argument('--'+key,required=True)
    main(p.parse_args())
