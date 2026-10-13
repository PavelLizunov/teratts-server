"""Whole-WAV GigaAM Multilingual CTC: fixed native greedy/beam/context comparison.

Exploratory corpus reuse, not a fresh holdout. Context bias changes decoding,
not weights or trained language inventory. Private receipts never enter Git.
"""
import argparse
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
import wave

from ctc_context import search
from decoder import ContextBias
from mms_pair import digest, save
from pilot import rss_bytes
from run import Guard, memory_snapshot, sensors

MODEL_FILES = {
    'pytorch_model.bin': 'c3fabefb50b41f08f4d7ad44e02c26c37d242882704cdcca2ebd98e45eff73d1',
    'modeling_gigaam.py': '6d02e640fbb5738ab11c030520a68654ef32f4ff363723db10534cf8b5d5c0e7',
    'config.json': '5ea1089c77b60e094352d7fb7bfb6580906b380c4dc7053edb4f7f0a1f59c172',
}
REVISION = '3905cd51c3ed4e88c8edf33f3302969ba480a327'
HINTS = ('ChatGPT', 'ChatGPT Pro', 'DSH', 'Oracle')


def load_model(root):
    import torch
    from omegaconf import OmegaConf
    for name, expected in MODEL_FILES.items():
        if digest(root / name) != expected:
            raise ValueError('Changed original model asset: ' + name)
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    spec = importlib.util.spec_from_file_location('modeling_gigaam', root / 'modeling_gigaam.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    cfg = json.loads((root / 'config.json').read_text())['cfg']['model']['cfg']
    if cfg['model_name'] != 'multilingual_large_ctc':
        raise ValueError('Unexpected GigaAM variant')
    # Retain every original tensor, including frontend buffers. The official
    # frontend performs scalar checks and cannot initialize under meta. Construct
    # normally, then replace initialized storage with exact mmap checkpoint tensors.
    state = torch.load(root / 'pytorch_model.bin', weights_only=True, mmap=True, map_location='cpu')
    if not all(k.startswith('model.') for k in state):
        raise ValueError('Unexpected original state keys')
    model = module.GigaAMASR(OmegaConf.create(cfg))
    loading = model.load_state_dict({k[len('model.'):]: v for k, v in state.items()}, strict=True, assign=True)
    model.eval()
    if any(x.device.type != 'cpu' for x in list(model.parameters()) + list(model.buffers())):
        raise ValueError('Model has unmaterialized tensors')
    vocab = cfg['decoding']['vocabulary']
    if len(vocab) != 70 or cfg['head']['num_classes'] != 71 or len(set(vocab)) != 70:
        raise ValueError('Unexpected trained vocabulary')
    return model, vocab, {'missing_keys': loading.missing_keys, 'unexpected_keys': loading.unexpected_keys}


def worker(cfg):
    import numpy as np
    import torch
    folder = Path(cfg['results_directory'])
    def offline(event, args):
        if event in ('socket.connect', 'socket.getaddrinfo'):
            raise RuntimeError('Inference network disabled')
    sys.addaudithook(offline)
    begin = time.monotonic()
    model, vocab, loading = load_model(Path(cfg['model']))
    blank = len(vocab)
    ids = {v: i for i, v in enumerate(vocab)}
    paths = [[ids[c] for c in hint.lower()] for hint in HINTS]
    save(folder / 'runtime.json', {
        'model': 'ai-sage/GigaAM-Multilingual', 'revision': REVISION,
        'files_sha256': MODEL_FILES, 'versions': {k: importlib.metadata.version(k) for k in
            ('torch', 'torchaudio', 'transformers', 'hydra-core', 'omegaconf', 'numpy')},
        'host': os.uname().nodename, 'device': 'cpu', 'dtype': 'float32', 'threads': 2,
        'load_and_verify_s': time.monotonic() - begin, 'loading': loading,
        'vocabulary': vocab, 'blank_id': blank, 'separate_language_heads': False,
        'language_mask': None, 'source_commit': cfg['source_commit'],
        'hints': HINTS, 'context_paths': paths, 'context_scope': 'character substring; no hard word boundary',
        'training': False, 'audio_segmentation': False, 'added_waveform_padding': False,
    })
    for clip in cfg['recordings']:
        out = folder / (clip['id'] + '.json')
        save(folder / (clip['id'] + '-started.json'), {'time_unix': time.time(), 'audio_sha256': clip['sha256']})
        start = time.monotonic()
        guard = Guard(600, cfg['rss_mib'])
        result = {'id': clip['id'], 'status': 'failed', 'audio_sha256': clip['sha256'],
                  'duration_s': clip['duration_s'], 'source_commit': cfg['source_commit']}
        try:
            if digest(clip['wav']) != clip['sha256']:
                raise ValueError('Original audio hash changed')
            with wave.open(clip['wav']) as wav:
                if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (1, 2, 16000, 'NONE'):
                    raise ValueError('Original PCM16 mono16k required')
                n = wav.getnframes()
                x = np.frombuffer(wav.readframes(n), dtype='<i2').astype(np.float32) / 32768
            if len(x) != n or abs(n / 16000 - clip['duration_s']) > .001:
                raise ValueError('Audio sample count changed')
            a = time.monotonic()
            with torch.inference_mode():
                encoded, length = model.forward(torch.from_numpy(x)[None], torch.tensor([n], dtype=torch.long))
                lp = model.head(encoded)[0, :int(length[0])].float().cpu().numpy()
            result['acoustic_s'] = time.monotonic() - a
            guard.check()
            if lp.ndim != 2 or lp.shape[1] != blank + 1 or not np.isfinite(lp).all():
                raise ValueError('Invalid native log probabilities')
            logits = folder / (clip['id'] + '.npz')
            with logits.open('xb') as f:
                np.savez_compressed(f, log_probs=lp)
            result.update(logits_sha256=digest(logits), native_shape=list(lp.shape), input_samples=n)
            raw_ids = lp.argmax(axis=1).tolist()
            kept = [t for j, t in enumerate(raw_ids) if t != blank and (j == 0 or t != raw_ids[j-1])]
            result['greedy'] = {'token_ids': kept, 'raw_text': ''.join(vocab[t] for t in kept),
                                'decoder': 'native argmax/collapse/blank removal'}
            variants = {}
            result['variants'] = variants
            for name, score in (('no_context', 0.0), ('context', 2.5)):
                a = time.monotonic()
                hypotheses = search(lp, range(blank), blank, ContextBias(paths if score else (), score), 32, guard.check)
                if not hypotheses:
                    raise ValueError('No CTC beam result')
                for h in hypotheses:
                    if any(t not in range(blank) for t in h['token_ids']):
                        raise ValueError('Output outside trained native vocabulary')
                    if h['context_credit'] > score * len(h['token_ids']) + 1e-8:
                        raise ValueError('Duplicate context credit')
                    h['raw_text'] = ''.join(vocab[t] for t in h['token_ids'])
                variants[name] = {'decode_s': time.monotonic() - a, 'beam': 32,
                                  'score_per_character': score, 'hypotheses': hypotheses}
            result['status'] = 'success'
        except Exception as e:
            result['error'] = type(e).__name__ + ': ' + str(e)
        finally:
            result.update(elapsed_s=time.monotonic() - start,
                          process_highwater_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                          guard=guard.receipt())
            save(out, result)
            print(json.dumps({k: result.get(k) for k in ('id', 'status', 'elapsed_s', 'error')}), flush=True)
        if result['status'] != 'success':
            # Retained logits/partial decode identify consumed work. No automatic
            # retry; independent untouched clips may follow ordinary content errors.
            if guard.stop_reason:
                raise RuntimeError('Resource guard stopped corpus worker')
    save(folder / 'complete.json', {'records': len(cfg['recordings']), 'total_worker_s': time.monotonic()-begin})


def supervise(path):
    cfg = json.loads(Path(path).read_text())
    source = Path(__file__).parent
    for name, sha in cfg['source_files'].items():
        if digest(source / name) != sha:
            raise ValueError('Changed pinned source: ' + name)
    memory = memory_snapshot()
    if memory['MemAvailable'] < (cfg['rss_mib'] + 2048) * 1048576:
        raise RuntimeError('Preflight capacity insufficient; no corpus cell dispatched')
    folder = Path(cfg['results_directory'])
    folder.mkdir(mode=0o700, exist_ok=False)
    start = time.monotonic()
    samples, reason, peak = [], None, 0
    cmd = [sys.executable, str(Path(__file__).resolve()), 'worker', str(path)]
    with (folder / 'worker.stdout').open('xb') as out, (folder / 'worker.stderr').open('xb') as err:
        proc = subprocess.Popen(['nice', '-n', '19', *cmd], stdout=out, stderr=err, start_new_session=True,
                                env=dict(os.environ, OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2',
                                         CUDA_VISIBLE_DEVICES='', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1'))
        try:
            while proc.poll() is None:
                current, sensor = memory_snapshot(), sensors()
                rss = rss_bytes(proc.pid)
                peak = max(peak, rss)
                sample = {'elapsed_s': time.monotonic()-start, 'rss_bytes': rss,
                          'available_bytes': current['MemAvailable'],
                          'swap_growth_bytes': current['swap_used']-memory['swap_used'], **sensor}
                samples.append(sample)
                if rss > cfg['rss_mib'] * 1048576: reason = 'rss_limit'
                if current['MemAvailable'] < 2048 * 1048576: reason = 'available_memory_floor'
                if sample['swap_growth_bytes'] > 256 * 1048576: reason = 'swap_growth_limit'
                if any(v >= 85000 for v in sensor['temperatures_millic'].values()): reason = 'thermal_limit'
                if time.monotonic()-start > 1800: reason = 'agent_selected_worker_1800s_limit'
                if reason: break
                time.sleep(.25)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired: os.killpg(proc.pid, signal.SIGKILL)
            code = proc.wait()
    save(folder / 'supervisor.json', {'exit_code': code, 'stop_reason': reason,
         'elapsed_s': time.monotonic()-start, 'peak_rss_bytes': peak,
         'manifest_sha256': digest(path), 'samples': samples, 'command': cmd,
         'limits_source': 'agent-selected experiment protection; not user deadline'})
    print(json.dumps({'exit_code': code, 'stop_reason': reason, 'elapsed_s': time.monotonic()-start}), flush=True)
    if code or reason: raise RuntimeError('Corpus worker stopped; inspect receipts, never repeat consumed cells')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=('run', 'worker'))
    p.add_argument('manifest')
    args = p.parse_args()
    if args.mode == 'run': supervise(args.manifest)
    else: worker(json.loads(Path(args.manifest).read_text()))
