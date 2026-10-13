"""Whole retained-array boundary diagnosis; changes neither audio nor ASR output."""
import argparse
import json
import math
from pathlib import Path
import resource
import time

from boundary_mass import analyze, controls, ctc_sequence, greedy_ids
from decoder import ContextBias
from interval_context import settle
from mms_pair import digest, save
from occurrence_diagnostic import pilot
from run import Guard
from subword_pair import BOUNDARY


def worker(manifest_path):
    import numpy as np
    cfg=json.loads(Path(manifest_path).read_text());out=Path(cfg['output']);start=time.monotonic();guard=Guard(600,1536)
    control=controls();save(out/'controls.json',control)
    em=Path(cfg['english_model']);ep=json.loads((em/'prepared.json').read_text());pieces={int(k):v for k,v in ep['vocab'].items()}
    if digest(em/'tokenizer.model')!=ep['tokenizer_sha256']:raise ValueError('Changed tokenizer')
    def decode(ids):return ''.join(pieces[t] for t in ids).replace('▁',' ').strip()
    rows=[]
    for item in cfg['recordings']:
        guard.check();before=time.monotonic()
        for k in ('eng','aux','prior_result'):
            if digest(item[k])!=item['hashes'][k]:raise ValueError('Changed frozen input')
        en=json.loads(Path(item['eng']).read_text());prior=json.loads(Path(item['prior_result']).read_text());aux=json.loads(Path(item['aux']).read_text())
        if len({r['audio_sha256'] for r in (en,prior,aux)})!=1:raise ValueError('Mixed original audio')
        if digest(em/'prepared.json')!=en['prepared_sha256']:raise ValueError('Changed trained mapping')
        array=Path(item['eng']).with_suffix('.npz')
        if digest(array)!=en['retained_array_sha256']:raise ValueError('Changed English array')
        with np.load(array) as f:lp=f['values'].astype(np.float64)
        lp[:,0]=-np.inf;lp-=np.logaddexp.reduce(lp,axis=1,keepdims=True)
        align=prior['alignment'];value=analyze(lp,align['english_phrases'],align['english_phrase_intervals'],1024,guard.check)
        score_error=abs(value['viterbi_score']-align['score'])
        trace=[r['state'] for r in align['english_trace']]
        if score_error>1e-8 or value['viterbi_state_trace']!=trace:raise ValueError('Reconstructed graph does not match saved Viterbi')
        for p,row in enumerate(value['phrases']):
            a,b=row['selected_first'],row['selected_last'];labels=row['target_ids'];window=lp[a:b+1]
            greedy=greedy_ids(window,1024);target_logp=ctc_sequence(window,labels,1024);greedy_logp=ctc_sequence(window,greedy,1024)
            path=prior['search']['hint_paths'][p];g=ContextBias([path['context_symbols']],2.5)
            def credit(tokens):
                total=0.;state=()
                for token in tokens:
                    piece=pieces[token];symbols=([BOUNDARY] if piece.startswith('▁') else [])+[token]
                    if piece=='▁':symbols=[BOUNDARY]
                    for s in symbols:
                        d,state=g.step(state,s);total+=d
                return total+settle(g,state)
            tc,gc=credit(labels),credit(greedy)
            row.update(target_text=decode(labels),greedy_token_ids=greedy,greedy_text=decode(greedy),
                       target_ctc_log_mass=target_logp if math.isfinite(target_logp) else None,
                       greedy_ctc_log_mass=greedy_logp,target_context_credit=tc,greedy_context_credit=gc,
                       target_minus_greedy_acoustic=target_logp-greedy_logp if math.isfinite(target_logp) else None,
                       target_minus_greedy_isolated_biased=target_logp+tc-greedy_logp-gc if math.isfinite(target_logp) else None,
                       interval_has_slack=(b-a+1)>row['minimum_ctc_frames'],
                       canonical_target_ids_not_all_spellings=True,not_mixed_decoder_counterfactual=True)
            labels_unique=sorted(set(labels))
            row['frame_evidence']=[{'frame':i,'center_s':i*.08,'in_selected':a<=i<=b,
                'top_token':int(lp[i].argmax()),'top_piece':pieces[int(lp[i].argmax())],
                'top_logp':float(lp[i].max()),'blank_logp':float(lp[i,1024]),
                'target_label_logp':{str(t):float(lp[i,t]) for t in labels_unique},
                'conditional_occupancy':row['occupancy'][i]} for i in range(len(lp))]
        value.update(id=item['id'],audio_sha256=en['audio_sha256'],source_commit=cfg['source_commit'],
                     viterbi_receipt_score_error=score_error,viterbi_trace_exact=True,
                     retained_array_sha256=en['retained_array_sha256'],prior_result_sha256=item['hashes']['prior_result'],
                     auxiliary_text=aux['hypotheses'][0]['raw_text'],final_text=prior['search']['hypotheses'][0]['postprocessed_text'],
                     elapsed_s=time.monotonic()-before,no_new_transcript=True,no_decoder_or_encoder_calls=True)
        save(out/(item['id']+'.json'),value);rows.append({'id':item['id'],'phrases':len(value['phrases']),'elapsed_s':value['elapsed_s']})
        print(item['id'],'phrases',len(value['phrases']),'seconds',round(value['elapsed_s'],3),flush=True)
    save(out/'summary.json',{'status':'success','rows':rows,'elapsed_s':time.monotonic()-start,
                            'peak_rss_mib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                            'guard':guard.receipt(),'new_model_calls':0,'human_gold_records':0})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('pilot','worker'));p.add_argument('manifest');a=p.parse_args()
    if a.mode=='worker':worker(a.manifest)
    else:pilot(a.manifest,worker_script=__file__)
