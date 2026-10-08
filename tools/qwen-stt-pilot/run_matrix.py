"""Sequential bounded native models, preserve every failed branch and exact provenance."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from run import atomic_json, rss_bytes, validate_record


def parse_output(kind, stdout):
    if kind == 'transcribe':
        lines = [line[6:] for line in stdout.splitlines() if line.startswith('text: ')]
        if len(lines) != 1:
            raise ValueError('missing or ambiguous native text field')
        return '' if lines[0] == '(empty)' else lines[0].strip()
    if kind == 'json':
        data = json.loads(stdout)
        if not isinstance(data, dict):
            raise ValueError('unexpected model JSON')
        return data.get('text', ' '.join(s.get('text', '') for s in data.get('segments', []))).strip()
    return stdout.strip()


def run_model(root, item, manifest):
    output = root / 'results' / item['id']
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    if (output / 'summary.json').exists():
        print('EXISTING_TERMINAL', item['id'], flush=True)
        return
    manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    records = json.loads(manifest.read_text())['records']
    rows = []
    failed = None
    lock = root / 'inference.lock'
    import fcntl
    with lock.open('a+') as lease:
        fcntl.flock(lease, fcntl.LOCK_EX)
        deadline = time.monotonic() + item.get('budget_s', 900)
        for row in sorted(records, key=lambda r: not r['synthetic']):
            result_path = output / (row['id'] + '.json')
            if result_path.exists():
                old = json.loads(result_path.read_text())
                if old['status'] != 'success':
                    failed = old.get('error', 'prior failure')
                    break
                rows.append(old)
                continue
            audio = validate_record(row)
            env = {k:v for k,v in os.environ.items() if k in ['PATH','HOME','LANG']}
            env.update(OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', CUDA_VISIBLE_DEVICES='',
                       HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
            env.update(item.get('environment', {}))
            args = [s.replace('{audio}', str(audio)) for s in item['command']]
            start = time.monotonic()
            peak = 0
            reason = None
            with (output / (row['id'] + '.stdout')).open('wb') as out, (output / (row['id'] + '.stderr')).open('wb') as err:
                proc = subprocess.Popen(['nice', '-n', '19', *args], env=env, stdout=out, stderr=err, start_new_session=True)
                while proc.poll() is None:
                    peak = max(peak, rss_bytes(proc.pid))
                    if peak > item.get('rss_limit_bytes', 8_000_000_000): reason='memory_budget'
                    if time.monotonic() >= deadline: reason='time_budget'
                    if reason:
                        os.killpg(proc.pid, signal.SIGTERM)
                        try: proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(proc.pid, signal.SIGKILL); proc.wait()
                        break
                    time.sleep(.1)
                code = proc.wait()
            stdout = (output / (row['id'] + '.stdout')).read_text()
            error = reason or (f'exit_{code}' if code else None)
            text = None
            if not error:
                try: text = parse_output(item['kind'], stdout)
                except (ValueError, TypeError) as e: error = f'output_parse: {e}'
            result = dict(id=row['id'], audio_sha256=row['sha256'], model_id=item['id'],
                          status='failed' if error else 'success', exit_code=code, error=error,
                          text=text, elapsed_s=time.monotonic()-start, peak_rss_bytes=peak,
                          manifest_sha256=manifest_sha, command=args, hints=False,
                          provenance=item['provenance'])
            atomic_json(result_path, result)
            rows.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            if error:
                failed=error
                break
    atomic_json(output / 'summary.json', dict(model_id=item['id'],
                status='failed' if failed or len(rows)!=len(records) else 'complete',
                error=failed, completed=sum(r['status']=='success' for r in rows),
                expected=len(records), manifest_sha256=manifest_sha, provenance=item['provenance']))


def main():
    p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('config');p.add_argument('manifest')
    a=p.parse_args();root=Path(a.root); items=json.loads(Path(a.config).read_text())
    for item in items:
        try: run_model(root,item,Path(a.manifest))
        except Exception as e:
            path=root/'results'/item['id'];path.mkdir(parents=True,exist_ok=True)
            atomic_json(path/'summary.json',dict(model_id=item['id'],status='failed',error=repr(e),completed=0,expected=7,provenance=item['provenance']))
            print('BRANCH_FAILED',item['id'],repr(e),flush=True)


if __name__=='__main__':main()
