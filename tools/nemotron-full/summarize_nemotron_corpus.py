"""Coverage and transcript disagreement report, NOT gold ASR accuracy.

Does not upload, correct original transcript, promote model or hide failed rows.
"""
import argparse
from collections import Counter
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import statistics

from run_nemotron_corpus import validate_manifest,MODEL_SHA
from nemotron_corpus_snapshot import atomic_json


def tokens(text):
    return re.findall(r'\w+',text.casefold().replace('ё','е'))


def percentile(values,fraction):
    if not values:return None
    values=sorted(values)
    return round(values[min(len(values)-1,int((len(values)-1)*fraction))],4)


def disagreement(primary,candidate):
    a,b=tokens(primary),tokens(candidate)
    ratio=SequenceMatcher(None,a,b,autojunk=False).ratio()
    # Difference ratio is not WER; reference is another recognizer, not truth.
    return {'same_normalized_text':a==b,'token_agreement_ratio':round(ratio,4),
            'primary_token_count':len(a),'candidate_token_count':len(b),
            'primary_number_tokens':[w for w in a if any(ch.isdigit() for ch in w)],
            'candidate_number_tokens':[w for w in b if any(ch.isdigit() for ch in w)],
            'category':'agreement' if a==b else 'substantial_difference' if ratio<0.70 else 'small_difference'}


def summarize(root):
    root=Path(root);manifest,digest=validate_manifest(root)
    rows=[];statuses=Counter();categories=Counter();timings=[];total_duration=0;empty_primary=0
    empty_to_nonempty=0;nonempty_to_empty=0;source_count=0;unresolved=[]
    for frozen in manifest['records']:
        sha=frozen['audio_sha256'];p=root/'results'/(sha+'.json')
        if not p.exists():
            unresolved.append(sha);continue
        result=json.loads(p.read_text())
        if result.get('audio_sha256')!=sha or result.get('manifest_sha256')!=digest or result.get('model_sha256')!=MODEL_SHA:
            raise ValueError('Result identity differs from frozen experiment')
        statuses[result['status']]+=1;source_count+=len(frozen['sources'])
        if result['status']!='completed':
            rows.append({'audio_sha256':sha,'status':result['status'],'sources':frozen['sources']});continue
        candidate=result['result']['text'];elapsed=result['elapsed_s'];timings.append(elapsed);total_duration+=frozen['duration_s']
        comparisons=[]
        for source in frozen['sources']:
            baseline=source.get('baseline_raw')
            if baseline is None:
                comparisons.append({'sample_id':source['sample_id'],'baseline_unavailable':True});continue
            compare=disagreement(baseline,candidate);categories[compare['category']]+=1
            if not baseline.strip():
                empty_primary+=1
                if candidate.strip():empty_to_nonempty+=1
            if baseline.strip() and not candidate.strip():nonempty_to_empty+=1
            comparisons.append({'sample_id':source['sample_id'],'baseline_raw':baseline,**compare})
        rows.append({'audio_sha256':sha,'status':'completed','duration_s':frozen['duration_s'],
                     'elapsed_s':elapsed,'candidate_text':candidate,'comparisons':comparisons})
    control=root/'silence-control.json'
    return {'frozen_manifest_sha256':digest,'model_sha256':MODEL_SHA,'total_unique_audio':manifest['unique_audio'],
            'total_source_records':manifest['eligible_sources'],'resolved_unique_audio':sum(statuses.values()),
            'statuses':dict(statuses),'unresolved_unique_audio':len(unresolved),'unresolved_hashes':unresolved,
            'coverage_complete':not unresolved,'successful_unique_audio':statuses['completed'],
            'resolved_source_records':source_count,'all_manifest_results_successful':not unresolved and set(statuses)=={'completed'},
            'source_selection_exclusions':manifest['source_counts'],'successful_audio_seconds':round(total_duration,3),
            'successful_request_seconds':round(sum(timings),3),'request_latency_p50_s':percentile(timings,0.5),
            'request_latency_p95_s':percentile(timings,0.95),'trial_real_time_factor':round(sum(timings)/total_duration,4) if total_duration else None,
            'baseline_comparison_categories':dict(categories),'empty_baseline_sources_compared':empty_primary,
            'empty_primary_nonempty_candidate':empty_to_nonempty,'nonempty_primary_empty_candidate':nonempty_to_empty,
            'silence_control':json.loads(control.read_text()) if control.exists() else None,
            'device':'cpu','production_vulkan_latency_comparable':False,'hints_used':False,
            'gold_accuracy_measured':False,'training_started':False,'production_switch':False,
            'caution':'Source text is unreviewed Parakeet output. Differences and empty transitions are review candidates, not proof of errors or gains.',
            'results':rows}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('output',type=Path)
    args=p.parse_args();data=summarize(args.root);atomic_json(args.output,data)
    print(json.dumps({k:v for k,v in data.items() if k not in ['results','unresolved_hashes']},ensure_ascii=False))
