#!/usr/bin/env python3
"""Report paired correction results, without labeling source transcripts gold WER."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import statistics

p = argparse.ArgumentParser()
p.add_argument('run_dir', type=Path)
p.add_argument('output', type=Path)
a = p.parse_args()
rows = [json.loads(s) for s in (a.run_dir/'rows.jsonl').read_text().splitlines()]
summary = json.loads((a.run_dir/'summary.json').read_text())
result = {'execution': summary, 'paired_source_edits': {}, 'controls': [], 'user_examples': []}
for language in ['mixed', 'ru', 'en']:
    selected = [r for r in rows if r['kind'] == 'retained_pilot' and r['language'] == language]
    if not selected:
        continue
    total = sum(r['reference_words'] for r in selected)
    raw = sum(r['raw_edits'] for r in selected)
    fixed = sum(r['corrected_edits'] for r in selected)
    latin_reference = latin_raw = latin_fixed = 0
    for row in selected:
        ref = Counter(re.findall(r'[A-Za-z]+', row['reference'].casefold()))
        latin_reference += sum(ref.values())
        latin_raw += sum((ref & Counter(re.findall(r'[A-Za-z]+', row['input'].casefold()))).values())
        latin_fixed += sum((ref & Counter(re.findall(r'[A-Za-z]+', row['output'].casefold()))).values())
    result['paired_source_edits'][language] = {
        'n': len(selected), 'reference_words': total, 'raw_edits': raw, 'corrected_edits': fixed,
        'raw_ratio': raw/total, 'corrected_ratio': fixed/total,
        'improved': sum(r['corrected_edits'] < r['raw_edits'] for r in selected),
        'equal': sum(r['corrected_edits'] == r['raw_edits'] for r in selected),
        'worse': sum(r['corrected_edits'] > r['raw_edits'] for r in selected),
        'reference_latin_count': latin_reference, 'raw_latin_matches': latin_raw, 'corrected_latin_matches': latin_fixed,
        'median_wall_s': statistics.median(r['wall_s'] for r in selected)}
for row in rows:
    if row['kind'] == 'synthetic_control':
        result['controls'].append({k: row[k] for k in ['id', 'input', 'output', 'missing_literals', 'input_latin_count', 'retained_latin_count', 'wall_s']})
    if row['kind'] == 'user_supplied_text':
        result['user_examples'].append({k: row[k] for k in ['id', 'input', 'output', 'wall_s']})
latencies = sorted(r['wall_s'] for r in rows if r['kind'] != 'smoke')
result['wall_s'] = {'n': len(latencies), 'median': statistics.median(latencies), 'min': min(latencies), 'max': max(latencies)}
result['limits'] = 'Short selection screen. Source references not human-adjudicated; no claim of production WER, natural technical-name recovery or load stability. Controls are synthetic and small.'
with a.output.open('x') as target:
    json.dump(result, target, ensure_ascii=False, indent=2)
print(json.dumps(result, ensure_ascii=False, indent=2))
