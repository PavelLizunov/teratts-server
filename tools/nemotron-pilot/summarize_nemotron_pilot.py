"""Evidence-only paired summary; do not compute true WER from model baselines."""
from difflib import SequenceMatcher
import json
from pathlib import Path
import re


def tokens(text):return re.findall(r'\w+',text.casefold().replace('ё','е'))


def summarize(root):
    rows=[json.loads(p.read_text()) for p in sorted(Path(root).glob('*.record.json'))]
    plain={r['sample_id']:r for r in rows if r.get('mode')=='plain'}
    hinted={r['sample_id']:r for r in rows if r.get('mode')=='hinted'}
    pairs=[]
    for sid,before in plain.items():
        if sid not in hinted:continue
        after=hinted[sid]
        a=(before.get('result')or{}).get('text','');b=(after.get('result')or{}).get('text','')
        diagnostics=after.get('diagnostic_tail','')
        context_disabled=('boosting disabled' in diagnostics or 'no phrases could be tokenized' in diagnostics)
        pairs.append({'sample_id':sid,'category':before.get('category'),'same_normalized_text':tokens(a)==tokens(b),
          'context_disabled':context_disabled,'plain_text':a,'hinted_text':b,'parakeet_recorded_raw':before.get('baseline_raw'),
          'plain_cold_cli_seconds':before.get('wall_seconds_cold_cli'),'hinted_cold_cli_seconds':after.get('wall_seconds_cold_cli')})
    return {'records':len(rows),'pairs':pairs,'paired_count':len(pairs),
      'text_changed_pairs':sum(not p['same_normalized_text'] for p in pairs),
      'context_disabled_pairs':sum(p['context_disabled'] for p in pairs),
      'silence_plain':(plain.get('synthetic-silence',{}).get('result')or{}).get('text'),
      'silence_hinted':(hinted.get('synthetic-silence',{}).get('result')or{}).get('text'),
      'plain_cold_cli_total_s':round(sum(r.get('wall_seconds_cold_cli',0) for r in plain.values()),3),
      'hinted_cold_cli_total_s':round(sum(r.get('wall_seconds_cold_cli',0) for r in hinted.values()),3),
      'accuracy_measured':False,'gold_reference_available':False,'production_vulkan_speed_compared':False,
      'limitation':'CPU quota one core, cold CLI model loads. ASR baseline is unreviewed primary output, not gold.'}


if __name__=='__main__':
    import argparse,os
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('output',type=Path);args=p.parse_args()
    result=summarize(args.root);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2));args.output.chmod(0o600)
    print(json.dumps({k:v for k,v in result.items() if k!='pairs'},ensure_ascii=False))
