"""Isolated alternate CTC/frontend cells, retaining logits for acoustic decoding."""
import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

from run import Guard, digest, features_from_wav, memory_snapshot, sensors
from pilot import rss_bytes
from frontend import nemo_features

CTC_EXPORTS = {
    'int8': ('model.int8.onnx', 'e3ea888bcc90cafdeeedeea26f6e8ca2186d8af7939236e0eb246206f5098c00'),
    'fp32': ('model.onnx', 'b0e77792202b0113e8439b5cff88e24119016f861425940a45f57568137dec4b'),
}


def cell(args):
    import numpy as np
    import onnxruntime as ort
    root, output = Path(args.root), Path(args.output)
    if output.exists() or output.with_suffix('.npz').exists():
        raise FileExistsError('Consumed/unknown cell must not be repeated')
    started = time.monotonic()
    receipt = {'status': 'failed', 'parameters': vars(args), 'source_commit': subprocess.check_output(
        ['git', '-C', str(Path(__file__).parent), 'rev-parse', 'HEAD'], text=True).strip(),
        'trial_started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'postprocessing': 'none', 'segmentation': False, 'appended_audio_padding': False}
    guard = None
    try:
        guard = Guard(180, 1536)
        artifacts = json.loads((root / 'prepared/artifacts.json').read_text())
        for name, sha in artifacts['files_sha256'].items():
            if digest(root / 'prepared' / name) != sha:
                raise ValueError('Prepared artifact changed: ' + name)
        if digest(root / args.wav) != args.audio_sha256:
            raise ValueError('Original audio changed')
        filename, model_sha = CTC_EXPORTS[args.precision]
        model_root = root / ('ctc-' + args.precision)
        model_path = model_root / filename
        if digest(model_path) != model_sha or digest(model_root / 'tokens.txt') != digest(root / 'prepared/tokens.txt'):
            raise ValueError('CTC export/token map mismatch')
        feature_fn = nemo_features if args.frontend == 'nemo' else features_from_wav
        feats, duration = feature_fn(root / args.wav, artifacts['preprocessor'])
        options = ort.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        model = ort.InferenceSession(str(model_path), sess_options=options, providers=['CPUExecutionProvider'])
        receipt['model_metadata'] = model.get_modelmeta().custom_metadata_map
        receipt['model_signature'] = {'inputs': [str(x) for x in model.get_inputs()], 'outputs': [str(x) for x in model.get_outputs()]}
        if receipt['model_metadata']['normalize_type'] != 'per_feature':
            raise ValueError('Unexpected CTC normalization')
        guard.check()
        logits = model.run(None, {model.get_inputs()[0].name: feats.T[None],
                                 model.get_inputs()[1].name: np.array([len(feats)], dtype=np.int64)})[0][0]
        guard.check()
        blank = artifacts['blank_id']
        if logits.shape[1] != blank + 1 or not np.isfinite(logits).all():
            raise ValueError('Invalid class dimension or nonfinite logits')
        # Reuse retained acoustic probabilities for subsequent context search,
        # rather than launching the encoder again on consumed recordings.
        np.savez_compressed(output.with_suffix('.npz'), log_probs=logits)
        allowed = np.array(sorted(set(artifacts['allowed_token_ids']) | {blank}), dtype=np.int64)
        path = allowed[np.argmax(logits[:, allowed], axis=1)]
        ids, frames = [], []
        previous = blank
        for frame, token in enumerate(path.tolist()):
            if token != blank and token != previous:
                ids.append(token)
                frames.append(frame)
            previous = token
        pieces = {}
        for line in (root / 'prepared/tokens.txt').read_text().splitlines():
            text, i = line.rsplit(' ', 1)
            pieces[int(i)] = text
        text = ''.join(pieces[i] for i in ids).replace('▁', ' ').strip()
        receipt.update(status='success', token_ids=ids, frame_indices=frames, raw_text=text,
                       postprocessed_text=text, audio_sha256=args.audio_sha256, model_sha256=model_sha,
                       feature_frames=len(feats), encoded_frames=len(logits), audio_duration_s=duration,
                       allowed_token_ids=allowed.tolist(), blank_id=blank,
                       ctc_path_log_prob=float(logits[np.arange(len(logits)), path].sum()),
                       retained_logits_sha256=digest(output.with_suffix('.npz')),
                       runtime_versions={'numpy': np.__version__, 'onnxruntime': ort.__version__})
    except Exception as error:
        receipt['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        receipt.update(elapsed_s=time.monotonic() - started,
                       peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                       guard=guard.receipt() if guard else None)
        with output.open('x') as out:
            json.dump(receipt, out, ensure_ascii=False, indent=2)
        print(json.dumps(receipt, ensure_ascii=False), flush=True)


def supervise(root, manifest_name):
    root = Path(root)
    manifest_path = root / manifest_name
    manifest = json.loads(manifest_path.read_text())
    results = root / manifest['results_directory']
    results.mkdir(mode=0o700, exist_ok=False)
    initial = memory_snapshot()
    for item in manifest['cells']:
        name = item['id']
        if Path(name).name != name:
            raise ValueError('Invalid cell ID')
        command = [sys.executable, str(Path(__file__).resolve()), 'cell', '--root', str(root),
                   '--output', str(results / (name + '.json')), '--wav', item['wav'],
                   '--audio-sha256', item['audio_sha256'], '--frontend', item['frontend'],
                   '--precision', item.get('precision', 'int8')]
        started, peak, reason, samples = time.monotonic(), 0, None, []
        with (results / (name + '.stdout')).open('xb') as out, (results / (name + '.stderr')).open('xb') as err:
            proc = subprocess.Popen(['nice', '-n', '19', *command], stdout=out, stderr=err,
                                    env=dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1'))
            try:
                while proc.poll() is None:
                    peak = max(peak, rss_bytes(proc.pid))
                    mem, sensor = memory_snapshot(), sensors()
                    sample = {'elapsed_s': time.monotonic() - started, 'rss_bytes': peak,
                              'available_bytes': mem['MemAvailable'],
                              'swap_growth_bytes': mem['swap_used'] - initial['swap_used'], **sensor}
                    samples.append(sample)
                    if peak > 1536 * 1048576: reason = 'rss_limit'
                    if mem['MemAvailable'] < 2048 * 1048576: reason = 'available_memory_floor'
                    if sample['swap_growth_bytes'] > 256 * 1048576: reason = 'swap_limit'
                    if any(x >= 85000 for x in sensor['temperatures_millic'].values()): reason = 'thermal_limit'
                    if time.monotonic() - started > 180: reason = 'timeout'
                    if reason: break
                    time.sleep(.25)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try: proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                code = proc.wait()
        receipt = {'id': name, 'exit_code': code, 'stop_reason': reason,
                   'elapsed_s': time.monotonic() - started, 'peak_rss_bytes': peak,
                   'samples': samples, 'manifest_sha256': digest(manifest_path), 'command': command}
        with (results / (name + '-supervisor.json')).open('x') as out:
            json.dump(receipt, out, indent=2)
        print(json.dumps({k: v for k, v in receipt.items() if k not in ('samples', 'command')}), flush=True)
        if reason: raise RuntimeError('Protective stop: ' + reason)
        if code: raise RuntimeError('Failed cell retained; diagnose before untouched cells')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='mode', required=True)
    c = sub.add_parser('cell')
    for name in ('root', 'output', 'wav', 'audio-sha256'):
        c.add_argument('--' + name, required=True)
    c.add_argument('--frontend', required=True, choices=('knf', 'nemo'))
    c.add_argument('--precision', choices=('int8', 'fp32'), default='int8')
    p = sub.add_parser('pilot')
    p.add_argument('root')
    p.add_argument('manifest')
    args = parser.parse_args()
    if args.mode == 'cell': cell(args)
    else: supervise(args.root, args.manifest)
