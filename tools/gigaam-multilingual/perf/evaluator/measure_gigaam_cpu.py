"""Balanced fixed-fixture runtime experiment, single in-memory model, no private output logs."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import resource
import time


def signature(output):
    return {'text':output['text'], 'segments':output['segments'], 'audio_duration_s':output['audio_duration_s']}


def matches(expected, observed):
    return signature(expected) == signature(observed)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--threads',type=int,default=2);parser.add_argument('--confirmation',action='store_true')
    parser.add_argument('--commit',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args()
    import torch
    import gigaam_multilingual_server as adapter
    runner=adapter.Recognizer(Path('/home/deck/homelab/gigaam-multilingual-20261005/models'))
    references=json.loads((args.root/'reference-private.json').read_text())
    selected=references[2:] if args.confirmation else references[:2]
    pairs=[];checks=[];observations=[]
    for row in selected:
        raw=(args.root/'audio'/row['file']).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==row['audio_sha256']
        for threads in {2,args.threads}:
            torch.set_num_threads(threads); checks.append(matches(row['output'],runner.transcribe(raw)))
    baseline=[];candidate=[]
    for round_no in range(3):
        order=[2,args.threads] if round_no%2==0 else [args.threads,2]
        for trial,threads in enumerate(order):
            torch.set_num_threads(threads)
            start=time.perf_counter()
            for row in selected:
                output=runner.transcribe((args.root/'audio'/row['file']).read_bytes())
                checks.append(matches(row['output'],output))
            elapsed=time.perf_counter()-start
            target=baseline if (threads==2 and (args.threads!=2 or trial==round_no%2)) else candidate
            target.append(elapsed)
            mem=int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))*1024
            temperatures=[int(p.read_text())/1000 for p in Path('/sys/class/thermal').glob('thermal_zone*/temp')]
            temperature=max(temperatures,default=0)
            if mem<2*1024**3 or temperature>=85:raise RuntimeError('Resource stop')
            observations.append({'threads':threads,'wall_s':elapsed,'available_bytes':mem,'temperature_c':temperature})
    original=selected[0]['output'];empty=copy.deepcopy(original);empty['text']=''
    removed=copy.deepcopy(original);removed['segments']=[]
    corrupt=copy.deepcopy(original);corrupt['segments'][0]['end_s']+=.01
    negative={'empty_output':not matches(original,empty),'collapsed_timeline':not matches(original,removed),'corrupt_boundary':not matches(original,corrupt)}
    result={'commit':args.commit,'threads':args.threads,'workload':'confirmation-v1' if args.confirmation else 'search-v1',
            'control':baseline,'candidate':candidate,'checks':{'exact_transcript_and_segments':all(checks)},'negative_controls':negative,
            'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,'observations':observations}
    out=args.root/args.output
    if out.exists():raise RuntimeError('Immutable evidence exists')
    out.write_text(json.dumps(result,indent=2));out.chmod(0o600);print(json.dumps(result),flush=True)
    if not all(checks) or not all(negative.values()):raise RuntimeError('Quality failure')

if __name__=='__main__':main()
