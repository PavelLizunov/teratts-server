"""Verify paired results and freeze neutral shuffled text, not gold/model promotion."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import secrets
import statistics


def collect(root):
    root=Path(root);m=json.loads((root/'manifest-private.json').read_text());digest=hashlib.sha256((root/'manifest-private.json').read_bytes()).hexdigest()
    results={};metrics={};pairs=[]
    for name in ['whisper','gigaam']:
        folder=root/'results'/name;complete=json.loads((folder/'complete.json').read_text());runtime=json.loads((folder/'runtime.json').read_text())
        if complete.get('results')!=18 or complete.get('manifest_sha256')!=digest or not complete.get('complete'):raise ValueError('Incomplete model')
        rows=[json.loads((folder/f'{i:02d}.json').read_text()) for i in range(1,19)]
        for source,row in zip(m['records'],rows):
            if not row.get('success') or not row.get('no_hints') or row.get('audio_sha256')!=source['audio_sha256'] or row.get('manifest_sha256')!=digest:raise ValueError('Mismatched result')
            if not isinstance(row.get('text'),str):raise ValueError('No transcript')
        results[name]=rows;durations=[r['seconds'] for r in rows]
        metrics[name]={'completed':len(rows),'load_seconds':runtime['load_seconds'],'cpu_inference_seconds':sum(durations),
            'median_request_seconds':statistics.median(durations),'control_texts':[{ 'control':m['records'][i]['sample_id'],'text':r['text']} for i,r in enumerate(rows) if r['category']=='negative_control'],
            'empty_real_clips':sum(not r['text'].strip() for r in rows if r['category']!='negative_control'),
            'unknown_markers':sum(r['text'].count('<unk>') for r in rows),'runtime':runtime}
    assignments_path=root/'private-neutral-assignments.json'
    if assignments_path.exists():assign=json.loads(assignments_path.read_text())
    else:
        sides=[True]*8+[False]*8;secrets.SystemRandom().shuffle(sides)
        assign=[{'token':secrets.token_hex(16),'option1_whisper':side} for side in sides]
        assignments_path.write_text(json.dumps(assign,indent=2));assignments_path.chmod(0o600)
    if len(assign)!=16 or sum(a['option1_whisper'] for a in assign)!=8:raise ValueError('Invalid balanced assignments')
    for i,source in enumerate(m['records'][:16]):
        a=assign[i];first='whisper' if a['option1_whisper'] else 'gigaam';second='gigaam' if first=='whisper' else 'whisper'
        pairs.append({'token':a['token'],'duration_s':source['duration_s'],'category':source['category'],
                      'option1_text':results[first][i]['text'],'option2_text':results[second][i]['text'],
                      'human_gold':False,'training_approved':False})
    return {'manifest_sha256':digest,'total_real_clips':16,'control_clips':2,'paired_results':36,'metrics':metrics,
            'no_accuracy_claim':True,'production_changed':False},pairs


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();report,pairs=collect(a.root)
    for name,value in [('summary-private.json',report),('neutral-pairs-private.json',pairs)]:
        f=a.root/name;f.write_text(json.dumps(value,ensure_ascii=False,indent=2));f.chmod(0o600)
    print(json.dumps({'paired_results':report['paired_results'],'metrics':{name:{k:v for k,v in r.items() if k!='runtime'} for name,r in report['metrics'].items()}},ensure_ascii=False))
