"""Recompute only auxiliary English phrase timing from the new compact scores."""
import argparse
import json
from pathlib import Path
import time
from mms_pair import digest, save
from phrase_guidance import align_phrases
from run import Guard


def main(args):
    import numpy as np
    ep,rp,ap,out=map(Path,(args.english,args.russian,args.alignment,args.output))
    if out.exists() or out.with_name(out.stem+'-alignment.json').exists():raise FileExistsError('Consumed timing integration')
    en,ru,prior=(json.loads(p.read_text()) for p in (ep,rp,ap))
    if len({en['audio_sha256'],ru['audio_sha256'],prior['audio_sha256']})!=1:raise ValueError('Different recordings')
    if digest(ep.with_suffix('.npz'))!=en['retained_logits_sha256']:raise ValueError('Changed scores')
    with np.load(ep.with_suffix('.npz')) as f:lp=f['log_probs'].astype(np.float64)
    lp[:,0]=-np.inf;lp-=np.logaddexp.reduce(lp,axis=1,keepdims=True)
    events=[{'head':'eng','native_frame':i,'center_s':i*.08,'log_probs':r} for i,r in enumerate(lp)]
    events.extend({'head':'rus','native_frame':i,'center_s':i*.04+ru['nominal_origin_s']} for i in range(ru['native_output_frames']))
    events.sort(key=lambda e:e['center_s']);start=time.monotonic();guard=Guard(180,1536)
    _,alignment=align_phrases(events,prior['label_path'],guard.check)
    alignment.update(audio_sha256=en['audio_sha256'],label_path=prior['label_path'],parent_alignment_sha256=digest(ap),english_receipt_sha256=digest(ep),russian_receipt_sha256=digest(rp))
    path=out.with_name(out.stem+'-alignment.json');save(path,alignment)
    save(out,{'status':'success','audio_sha256':en['audio_sha256'],'alignment_sha256':digest(path),'english_receipt_sha256':digest(ep),'routing_english_receipt_sha256':digest(ep),'parent_alignment_sha256':digest(ap),'elapsed_s':time.monotonic()-start})
    print(json.dumps(alignment['english_phrase_intervals'],indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('english','russian','alignment','output'):p.add_argument('--'+k,required=True)
    main(p.parse_args())
