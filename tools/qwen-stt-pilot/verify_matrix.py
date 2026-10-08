"""Validate every successful candidate's fixed audio/manifest hash and terminal count."""
import argparse
import hashlib
import json
from pathlib import Path


def verify(matrix, manifest):
    matrix, manifest = Path(matrix), Path(manifest)
    expected = json.loads(manifest.read_text())['records']
    sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    by_id = {r['id']: r for r in expected}
    report = []
    for path in sorted((matrix / 'results').glob('*/summary.json')):
        summary = json.loads(path.read_text())
        rows = []
        for result_path in path.parent.glob('*.json'):
            if result_path.name in ['summary.json', 'presentation-status.json']:
                continue
            row = json.loads(result_path.read_text())
            if row.get('status') != 'success':
                continue
            if row['id'] not in by_id or row['audio_sha256'] != by_id[row['id']]['sha256']:
                raise ValueError('wrong original audio ' + str(result_path))
            if row['manifest_sha256'] != sha or row['hints'] is not False or row['exit_code'] != 0:
                raise ValueError('invalid successful receipt ' + str(result_path))
            if not isinstance(row['text'], str):
                raise ValueError('invalid transcript')
            rows.append(row)
        if summary['status'] == 'complete':
            if len(rows) != 7 or len({r['id'] for r in rows}) != 7:
                raise ValueError('false complete ' + str(path))
            if summary['completed'] != 7:
                raise ValueError('invalid complete count')
        report.append(dict(model=summary['model_id'], status=summary['status'],
                           validated_success=len(rows), error=summary.get('error')))
    return dict(manifest_sha256=sha, successful_branches=sum(r['status']=='complete' for r in report),
                branches=report, accuracy='No gold references; no WER calculated')


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('matrix');p.add_argument('manifest');p.add_argument('output')
    a=p.parse_args();data=verify(a.matrix,a.manifest);Path(a.output).write_text(json.dumps(data,ensure_ascii=False,indent=2));print(json.dumps(data,ensure_ascii=False,indent=2))
