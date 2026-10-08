"""Bounded native Qwen pilot; exact WAV hash, no transcript hints, RSS guard."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def validate_record(row):
    path = Path(row['path'])
    if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
        raise ValueError('audio changed: ' + row['id'])
    return path


def rss_bytes(pid):
    try:
        for line in Path(f'/proc/{pid}/status').read_text().splitlines():
            if line.startswith('VmRSS:'):
                return int(line.split()[1]) * 1024
    except FileNotFoundError:
        pass
    return 0


def atomic_json(path, value):
    temp = path.with_suffix('.part')
    with temp.open('w') as out:
        json.dump(value, out, ensure_ascii=False, indent=2)
        out.flush()
        os.fsync(out.fileno())
    temp.chmod(0o600)
    temp.replace(path)


def run(root, seconds=900, memory_limit=8_000_000_000):
    root = Path(root)
    manifest_path = root / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    output = root / 'qwen-results'
    output.mkdir(mode=0o700, exist_ok=True)
    if list(output.glob('*.json')):
        raise FileExistsError('Refuse to overwrite trial results')
    model_receipt = json.loads((root / 'model-receipt.json').read_text())
    if len(model_receipt) != 10 or sum(r['bytes'] for r in model_receipt) < 4_600_000_000:
        raise ValueError('incomplete model receipt')
    for r in model_receipt:
        p = root / 'model' / r['file']
        if p.stat().st_size != r['bytes']:
            raise ValueError('model size changed')
    source_revision = subprocess.check_output(['git', '-C', str(root / 'native-source'), 'rev-parse', 'HEAD'], text=True).strip()
    blas = root / 'blas/root/usr/lib/x86_64-linux-gnu'
    env = {k: v for k, v in os.environ.items() if k in ['PATH', 'HOME', 'LANG']}
    env.update(OPENBLAS_NUM_THREADS='2', OMP_NUM_THREADS='2',
               LD_LIBRARY_PATH=str(blas) + ':' + str(blas / 'openblas-pthread'))
    deadline = time.monotonic() + seconds
    # Short negative controls first make an accidental speech hallucination visible early.
    rows = sorted(manifest['records'], key=lambda r: not r['synthetic'])
    for row in rows:
        path = validate_record(row)
        if time.monotonic() >= deadline:
            raise TimeoutError('pilot total budget expired')
        args = [str(root / 'native-source/qwen_asr'), '-d', str(root / 'model'),
                '-i', str(path), '-t', '2', '-S', '0', '--past-text', 'no',
                '--language', 'Russian', '--silent']
        stdout_path = output / (row['id'] + '.stdout')
        stderr_path = output / (row['id'] + '.stderr')
        peak = 0
        started = time.monotonic()
        reason = None
        with stdout_path.open('wb') as out, stderr_path.open('wb') as err:
            proc = subprocess.Popen(['nice', '-n', '19', *args], env=env, stdout=out, stderr=err)
            while proc.poll() is None:
                peak = max(peak, rss_bytes(proc.pid))
                if peak > memory_limit:
                    reason = 'memory_budget'
                if time.monotonic() >= deadline:
                    reason = 'time_budget'
                if reason:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    break
                time.sleep(.1)
            code = proc.wait()
        result = dict(id=row['id'], sha256=row['sha256'], synthetic=row['synthetic'],
                      model='Qwen/Qwen3-ASR-1.7B', model_revision=model_receipt[0]['revision'],
                      engine='antirez/qwen-asr', engine_revision=source_revision,
                      precision='original BF16 weights, native CPU kernels', host='harness-test CPU',
                      language='Russian', hints=False, manifest_sha256=manifest_sha,
                      elapsed_s=time.monotonic() - started, peak_rss_bytes=peak,
                      status='success' if code == 0 and not reason else 'failed',
                      exit_code=code, stop_reason=reason,
                      text=stdout_path.read_text().strip())
        atomic_json(output / (row['id'] + '.json'), result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if result['status'] != 'success':
            raise RuntimeError('candidate failed: ' + row['id'])
    print('ALL_SEVEN_COMPLETE', flush=True)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('root')
    run(p.parse_args().root)
