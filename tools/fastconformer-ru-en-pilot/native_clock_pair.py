"""Single open CTC search over selected native-clock RU/EN head events.

GigaAM40ms and Wav2Vec20ms are never interpolated or repeated. Full saved arrays
are intact. A fixed earlier model-derived language schedule routes native rows;
this is not independently calibrated LID. Text is not copied from its proposal.
"""
import argparse
from functools import lru_cache
import json
import math
from pathlib import Path
import resource
import subprocess
import time

from ctc_context import logadd, NEG
from decoder import ContextBias
from mms_pair import HINTS, digest, save
from run import Guard


def decode(events, tokens, head, delimiters, blank, paths, score, check):
    graph = ContextBias(paths if score else (), score)
    @lru_cache(maxsize=100000)
    def bias(prefix):
        if not prefix: return 0., ()
        old, state = bias(prefix[:-1])
        delta, state = graph.step(state, prefix[-1])
        return old+delta, state
    current = {(): (0., NEG)}
    previous = events[0]['head']
    switches = []
    for event in events:
        check()
        lang, row = event['head'], event['log_probs']
        if lang != previous:
            before = len(current)
            current = {prefix: masses for prefix, masses in current.items() if not prefix or prefix[-1] in delimiters}
            switches.append({'event': event['index'], 'from': previous, 'to': lang,
                             'closed_paths': len(current), 'pruned_unclosed_paths': before-len(current)})
            previous = lang
        if not current:
            raise ValueError('No delimiter-closed path at fixed native-clock switch')
        following = {}
        def add(prefix, pb=NEG, pnb=NEG):
            old_b, old_nb = following.get(prefix, (NEG, NEG))
            following[prefix] = logadd(old_b, pb), logadd(old_nb, pnb)
        for prefix, (pb, pnb) in current.items():
            total = logadd(pb, pnb)
            add(prefix, pb=total+float(row[blank[lang]]))
            last = prefix[-1] if prefix else None
            for token, local in head[lang].items():
                lp = float(row[local])
                if last == token:
                    add(prefix, pnb=pnb+lp)
                    if token not in delimiters:
                        add((*prefix, token), pnb=pb+lp)
                elif last in delimiters and token in delimiters:
                    continue
                else:
                    add((*prefix, token), pnb=total+lp)
        current = {p: following[p] for p in sorted(following,
                   key=lambda p:logadd(*following[p])+bias(p)[0], reverse=True)[:32]}
    results = []
    for prefix, masses in current.items():
        acoustic = logadd(*masses)
        if not math.isfinite(acoustic): continue
        credit, state = bias(prefix)
        if events[-1]['head'] == 'eng':
            delta, state = graph.step(state, 4)
            credit += delta
        credit += graph.finalize(state)
        raw = ''.join(tokens[t] for t in prefix).strip()
        results.append({'token_ids': list(prefix), 'raw_text': raw, 'postprocessed_text': raw,
                        'routed_native_ctc_logsum': acoustic, 'context_credit': credit,
                        'total_score': acoustic+credit})
    return {'hypotheses': sorted(results, key=lambda r:r['total_score'], reverse=True)[:5],
            'switch_handling': switches, 'beam':32, 'hint_bonus':score, 'context_paths':paths if score else []}


def main(args):
    import numpy as np
    ru_path, en_path, guide_path, output = map(Path, (args.russian, args.english, args.guidance, args.output))
    if output.exists(): raise FileExistsError('Consumed native-clock search')
    started = time.monotonic()
    ru, en, guide = (json.loads(p.read_text()) for p in (ru_path, en_path, guide_path))
    if len({ru['audio_sha256'], en['audio_sha256'], guide['audio_sha256']}) != 1:
        raise ValueError('Mixed original recordings')
    efile = en_path.with_name(en_path.stem+'-eng.npz')
    if digest(ru_path.with_suffix('.npz')) != ru['retained_logits_sha256'] or digest(efile) != en['heads']['eng']['retained_logits_sha256']:
        raise ValueError('Changed native head arrays')
    with np.load(ru_path.with_suffix('.npz')) as data: rlp = data['log_probs'].astype(np.float64)
    with np.load(efile) as data: elp = data['log_probs'].astype(np.float64)
    evocab = en['heads']['eng']['vocab']
    elp[:, [evocab['<s>'], evocab['</s>'], evocab['<unk>']]] = -np.inf
    elp -= np.logaddexp.reduce(elp, axis=1, keepdims=True)
    tokenfile = Path(args.russian_model) / 'tokens.txt'
    assets_path = tokenfile.parent / 'download-receipt.json'
    assets = json.loads(assets_path.read_text())
    if digest(assets_path) != ru['asset_receipt_sha256'] or digest(tokenfile) != next(r['sha256'] for r in assets['files'] if r['name']=='tokens.txt'):
        raise ValueError('Changed Russian trained vocabulary provenance')
    rtokens = {int(line.rsplit(' ',1)[1]): line.rsplit(' ',1)[0] for line in tokenfile.read_text().splitlines()}
    if rtokens[0] != ' ' or rtokens[33] != '<blk>': raise ValueError('Unexpected Russian map')
    tokens = {i:(' ' if p=='|' else p) for p,i in evocab.items() if p not in ('<pad>','<s>','</s>','<unk>')}
    tokens.update({32+i:p for i,p in rtokens.items() if i != 33})
    heads = {'eng':{i:i for i in tokens if i<32},'rus':{32+i:i for i in rtokens if i!=33}}
    delimiters = {4,32}
    paths = [[space,*[evocab['|' if c==' ' else c] for c in name.upper()],4]
             for name in HINTS for space in delimiters]
    def guidance(center):
        frame = max(0,min(len(guide['head_schedule'])-1, int((center*16000-199.5)//320)))
        return guide['head_schedule'][frame]
    events = []
    for lang,array,stride,origin in (('eng',elp,320,199.5),('rus',rlp,640,159.5)):
        for index,row in enumerate(array):
            center = (index*stride+origin)/16000
            if guidance(center)==lang:
                events.append({'head':lang,'native_frame':index,'center_s':center,'log_probs':row})
    events.sort(key=lambda e:e['center_s'])
    for i,event in enumerate(events):event['index']=i
    guard = Guard(180,1536)
    result = {'source_commit':subprocess.check_output(['git','-C',str(Path(__file__).parent),'rev-parse','HEAD'],text=True).strip(),
              'russian_receipt_sha256':digest(ru_path),'english_receipt_sha256':digest(en_path),'guidance_sha256':digest(guide_path),
              'audio_sha256':ru['audio_sha256'],'audio_or_encoder_rerun':False,'probability_interpolation':False,
              'per_region_decoders':False,'postprocessing':'none','head_offsets':{'eng':0,'rus':32},
              'native_rows':{lang:sum(e['head']==lang for e in events) for lang in heads},
              'selected_native_events':[{k:v for k,v in e.items() if k!='log_probs'} for e in events], 'variants':{}}
    try:
        for name,score in (('no-context',0.),('context',2.5)):
            before=time.monotonic()
            value=decode(events,tokens,heads,delimiters,{'eng':0,'rus':33},paths,score,guard.check)
            value['decode_s']=time.monotonic()-before
            save(output.with_name(output.stem+'-'+name+'.json'),value)
            result['variants'][name]=value
            print(name,value['hypotheses'][0]['raw_text'],flush=True)
        result['status']='success'
    except Exception as error:
        result.update(status='failed',error=type(error).__name__+': '+str(error))
        raise
    finally:
        result.update(elapsed_s=time.monotonic()-started,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,guard=guard.receipt())
        save(output,result)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for key in ('russian','english','guidance','russian-model','output'):parser.add_argument('--'+key,required=True)
    main(parser.parse_args())
