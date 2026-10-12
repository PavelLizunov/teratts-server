"""Read-only inventory of collected speech; never infer or change corpus entries."""
import argparse
from collections import Counter
import json
from pathlib import Path
import tarfile
import time


def inventory(root,output):
    root=Path(root);counts=Counter();rows=[];start=time.monotonic()
    for path in sorted(root.glob('*.tar')):
        if path.is_symlink():counts['symlink']+=1;continue
        try:
            with tarfile.open(path) as tar:
                member=tar.getmember('sample.json')
                if member.size>1048576:counts['oversized_metadata']+=1;continue
                m=json.load(tar.extractfile(member))
                counts['kind:'+str(m.get('kind'))]+=1
                if m.get('kind')!='stt':continue
                names=tar.getnames()
                headers=m.get('client_context',{}).get('headers',{})
                request=next((v for k,v in headers.items() if k.lower()=='x-request-id'),'')
                row={k:m.get(k) for k in ('sample_id','audio_sha256','audio_bytes','audio_origin','audio_duration_s','sample_rate','channels','sample_width','backend','human_reference_text','reference_status','raw_text','final_text','dictionary','cleanup','timings_ms')}
                row.update(filename=path.name,has_original_wav='original.wav' in names,synthetic_request=str(request).lower().startswith('synthetic'),
                           policy_fields={k:v for k,v in m.items() if any(t in k.lower() for t in ('consent','optout','opt_out','exclude','training','collect','privacy'))},
                           header_policy={k:v for k,v in headers.items() if any(t in k.lower() for t in ('consent','opt','corpus','privacy','dictionary'))})
                rows.append(row)
        except (OSError,ValueError,KeyError,tarfile.TarError) as e:counts['unreadable:'+type(e).__name__]+=1
    r={'root':str(root),'created_unix':time.time(),'counts':dict(counts),'stt_records':rows,'elapsed_s':time.monotonic()-start}
    p=Path(output);p.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    with p.open('x') as f:json.dump(r,f,ensure_ascii=False,indent=2)
    p.chmod(0o600)
    summary={k:v for k,v in r.items() if k!='stt_records'}
    summary['speech_origins']=dict(Counter(str(r['audio_origin']) for r in rows))
    summary['reference_statuses']=dict(Counter(str(r['reference_status']) for r in rows))
    summary['duration_bins']=dict(Counter('unknown' if not isinstance(r['audio_duration_s'],(float,int)) else '<2' if r['audio_duration_s']<2 else '2-30' if r['audio_duration_s']<=30 else '>30' for r in rows))
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('output');a=p.parse_args();inventory(a.root,a.output)
