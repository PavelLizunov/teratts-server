"""Sequential fixed manifest runner; external guards cover native ORT calls."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from run import digest, memory_snapshot, sensors


def rss_bytes(pid):
    try:
        for line in Path(f'/proc/{pid}/status').read_text().splitlines():
            if line.startswith('VmRSS:'):
                return int(line.split()[1]) * 1024
    except FileNotFoundError:
        pass
    return 0


def main(root):
    root = Path(root)
    manifest_path = root / 'pilot-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    results = root / 'results'
    results.mkdir(mode=0o700, exist_ok=True)
    if any(results.iterdir()):
        raise FileExistsError('Trial directory is not empty; no repeats or unknown duplicates')
    source = Path(__file__).parent
    initial_memory = memory_snapshot()
    for recording in manifest['recordings']:
        if digest(root / recording['file']) != recording['sha256']:
            raise ValueError('Audio changed before pilot')
        for variant in ('no-bias', 'bias'):
            name = recording['id'] + '-' + variant
            result_path = results / (name + '.json')
            command = [sys.executable, str(source / 'run.py'),
                       '--artifacts', str(root / 'prepared'),
                       '--wav', str(root / recording['file']),
                       '--audio-sha256', recording['sha256'],
                       '--output', str(result_path), '--seconds', '180',
                       '--max-rss-mib', '1536', '--threads', '1', '--beam', '4']
            command += ['--no-bias'] if variant == 'no-bias' else ['--hints', str(root / 'hints.json')]
            started = time.monotonic()
            peak = 0
            reason = None
            samples = []
            env = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
            with (results / (name + '.stdout')).open('xb') as out, (results / (name + '.stderr')).open('xb') as err:
                process = subprocess.Popen(['nice', '-n', '19', *command], env=env, stdout=out, stderr=err)
                while process.poll() is None:
                    peak = max(peak, rss_bytes(process.pid))
                    mem, sensor = memory_snapshot(), sensors()
                    sample = {'elapsed_s': time.monotonic() - started, 'rss_bytes': peak,
                              'available_bytes': mem['MemAvailable'],
                              'swap_growth_bytes': mem['swap_used'] - initial_memory['swap_used'], **sensor}
                    samples.append(sample)
                    if peak > 1536 * 1048576:
                        reason = 'process_rss_limit'
                    if mem['MemAvailable'] < 2048 * 1048576:
                        reason = 'available_memory_floor'
                    if sample['swap_growth_bytes'] > 256 * 1048576:
                        reason = 'swap_growth_limit'
                    if any(t >= 85000 for t in sensor['temperatures_millic'].values()):
                        reason = 'thermal_limit'
                    if time.monotonic() - started > 180:
                        reason = 'recording_timeout'
                    if reason:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                        break
                    time.sleep(.25)
                code = process.wait()
            observed = {'id': name, 'exit_code': code, 'stop_reason': reason,
                        'elapsed_s': time.monotonic() - started, 'peak_rss_bytes': peak,
                        'manifest_sha256': digest(manifest_path), 'command': command,
                        'samples': samples}
            with (results / (name + '-supervisor.json')).open('x') as file:
                json.dump(observed, file, ensure_ascii=False, indent=2)
            print(json.dumps({k: v for k, v in observed.items() if k not in ('samples', 'command')}, ensure_ascii=False), flush=True)
            if reason in ('process_rss_limit', 'available_memory_floor', 'swap_growth_limit', 'thermal_limit'):
                raise RuntimeError('Protective stop: ' + reason)
            if code != 0:
                print('Trial failed and retained; proceed only with untouched cells', flush=True)
    print('FOUR_FIXED_CELLS_FINISHED', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root')
    main(parser.parse_args().root)
