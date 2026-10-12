"""Local whole-recording MMS eng/rus adapter mixture; no semantic text repair.

Two complete adapter passes are necessary: language adapters modify every
transformer layer. Published head identity, not character script, defines the
pair restriction. Equal mixture weights are NOT calibrated language detection.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import wave

from ctc_context import search, WordLanguageConstraint
from decoder import ContextBias
from run import memory_snapshot, sensors
from pilot import rss_bytes

REV = '3d33597edbdaaba14a8e858e2c8caa76e3cec0cd'
LANGS = ('eng', 'rus')
HINTS = ('ChatGPT', 'ChatGPT Pro', 'DSH', 'Oracle')
LIMITS = {'seconds': 600, 'rss_mib': 8192, 'available_mib': 2048,
          'swap_growth_mib': 256, 'temperature_c': 85}


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as file:
        while block := file.read(8 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    with Path(path).open('x') as file:
        json.dump(value, file, ensure_ascii=False, indent=2)


def repair_weight_names(model, loading, model_root):
    """Migrate only the observed legacy weight_norm key pair, never values."""
    import torch
    prefix = 'wav2vec2.encoder.pos_conv_embed.conv.'
    migration = {prefix + 'weight_g': prefix + 'parametrizations.weight.original0',
                 prefix + 'weight_v': prefix + 'parametrizations.weight.original1'}
    if (set(loading.get('missing_keys', [])) == set(migration.values())
            and set(loading.get('unexpected_keys', [])) == set(migration)
            and not loading.get('mismatched_keys') and not loading.get('error_msgs')):
        from safetensors import safe_open
        with safe_open(Path(model_root) / 'model.safetensors', framework='pt', device='cpu') as file:
            renamed = {new: file.get_tensor(old) for old, new in migration.items()}
        model.load_state_dict(renamed, strict=False, assign=True)
        actual = model.state_dict()
        if any(not torch.equal(actual[key], tensor) for key, tensor in renamed.items()):
            raise ValueError('Legacy weight-normalization migration changed tensor values')
        return {'mapping': migration, 'tensor_values_equal': True, 'training': False,
                'remaining_missing_keys': []}
    if (loading.get('missing_keys') or loading.get('unexpected_keys')
            or loading.get('mismatched_keys') or loading.get('error_msgs')):
        raise ValueError('Model loader reports incomplete or unexpected acoustic weights')
    return {'mapping': {}, 'remaining_missing_keys': []}


def collapse(ids, vocab):
    pieces = {i: p for p, i in vocab.items()}
    kept, previous = [], None
    for token in ids:
        if token != previous and token != vocab['<pad>']:
            kept.append(int(token))
        previous = token
    return {'token_ids': kept, 'raw_text': ''.join(pieces[i] for i in kept).replace('|', ' ')}


def decode_pair(arrays, vocabs):
    import numpy as np
    if arrays['eng'].shape[0] != arrays['rus'].shape[0]:
        raise ValueError('Adapter time axes do not match')
    tokens, allowed, provenance, configs = {}, [], {}, {}
    offset = 0
    for lang, short in zip(LANGS, ('en', 'ru')):
        v = vocabs[lang]
        if sorted(v.values()) != list(range(len(v))):
            raise ValueError('Noncontiguous publisher vocabulary')
        configs[short] = {'offset': offset, 'size': len(v), 'unk_id': v['<unk>']}
        for text, local in v.items():
            token = local + offset
            tokens[token] = '▁' if text == '|' else text
            provenance[token] = {'adapter': lang, 'local_id': local, 'piece': text}
            if text not in ('<pad>', '<s>', '</s>', '<unk>'):
                allowed.append(token)
        offset += len(v)
    blank = offset
    mixed = np.full((arrays['eng'].shape[0], blank + 1), -np.inf, dtype=np.float64)
    for lang, short in zip(LANGS, ('en', 'ru')):
        off = configs[short]['offset']
        for local in range(len(vocabs[lang])):
            if off + local in allowed:
                mixed[:, off + local] = arrays[lang][:, local] - np.log(2.)
    mixed[:, blank] = np.logaddexp(arrays['eng'][:, vocabs['eng']['<pad>']],
                                 arrays['rus'][:, vocabs['rus']['<pad>']]) - np.log(2.)
    # The mixture is normalized before reserveds are masked. Renormalize once
    # after the mask, retaining equal head weights and a shared CTC blank.
    maxes = mixed.max(axis=1, keepdims=True)
    mixed -= maxes + np.log(np.exp(mixed - maxes).sum(axis=1, keepdims=True))
    artifacts = {'languages': configs}
    rule = WordLanguageConstraint(artifacts, tokens)
    paths = [[vocabs['eng']['|'], *[vocabs['eng']['|' if c == ' ' else c]
                                  for c in hint.lower()]] for hint in HINTS]
    variants = {}
    for name, score in (('no-context', 0.), ('context', 2.5)):
        context = ContextBias(paths if score else (), score)
        hypotheses = search(mixed, allowed, blank, context, 32, lambda: None, rule)
        if not hypotheses:
            raise ValueError('No finite bilingual path')
        for h in hypotheses:
            h['mixture_log_prob'] = h.pop('acoustic_log_prob')
            h['raw_text'] = ''.join(tokens[t] for t in h['token_ids']).replace('▁', ' ').strip()
            h['postprocessed_text'] = h['raw_text']
            h['word_language_rule'] = rule.receipt(h['token_ids'])
            h['adapter_counts'] = {lang: sum(provenance[t]['adapter'] == lang for t in h['token_ids']) for lang in LANGS}
            if any(t not in allowed for t in h['token_ids']) or h['word_language_rule']['within_word_violations']:
                raise ValueError('Output violates numerical pair/word constraint')
            if h['context_credit'] > score * len(h['token_ids']) + 1e-8:
                raise ValueError('Duplicate context credit')
        variants[name] = {'beam': 32, 'score': score, 'hints': list(HINTS) if score else [],
                          'context_paths': paths if score else [], 'hypotheses': hypotheses}
        print(name, hypotheses[0]['raw_text'], flush=True)
    return {'variants': variants, 'numeric_token_provenance': provenance, 'allowed_ids': allowed,
            'blank_id': blank, 'fusion': 'equal head-probability mixture, shared blank, reserved-token mask',
            'calibrated_language_detection': False}


def cell(args):
    output, model_root = Path(args.output), Path(args.model)
    if output.exists() or any(output.with_name(output.stem + '-' + lang + '.npz').exists() for lang in LANGS):
        raise FileExistsError('Consumed/unknown acoustic cell')
    start = time.monotonic()
    result = {'status': 'failed', 'parameters': vars(args), 'model_revision': REV,
              'source_commit': subprocess.check_output(['git', '-C', str(Path(__file__).parent), 'rev-parse', 'HEAD'], text=True).strip(),
              'host': os.uname().nodename, 'segmentation': False, 'audio_padding': False,
              'semantic_language_guarantee': False, 'allowed_trained_heads': list(LANGS), 'postprocessing': 'none',
              'trial_started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    try:
        import numpy as np
        import torch
        from transformers import Wav2Vec2FeatureExtractor, Wav2Vec2ForCTC
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        torch.manual_seed(0)
        result['runtime_versions'] = {k: importlib.metadata.version(k) for k in ('torch', 'transformers', 'accelerate', 'numpy', 'safetensors')}
        receipt = json.loads((model_root / 'download-receipt.json').read_text())
        if receipt['revision'] != REV:
            raise ValueError('Wrong model revision')
        for item in receipt['files']:
            if digest(model_root / item['name']) != item['sha256']:
                raise ValueError('Changed model asset: ' + item['name'])
        if digest(args.wav) != args.audio_sha256:
            raise ValueError('Original audio changed')
        result['asset_receipt_sha256'] = digest(model_root / 'download-receipt.json')
        vocabs = json.loads((model_root / 'vocab.json').read_text())
        with wave.open(args.wav, 'rb') as file:
            if (file.getnchannels(), file.getsampwidth(), file.getframerate(), file.getcomptype()) != (1, 2, 16000, 'NONE'):
                raise ValueError('Original mono16 PCM WAV required')
            count = file.getnframes()
            audio = np.frombuffer(file.readframes(count), dtype='<i2').astype(np.float32) / 32768.
        extractor = Wav2Vec2FeatureExtractor.from_pretrained(model_root, local_files_only=True)
        inputs = extractor(audio, sampling_rate=16000, padding=False, return_tensors='pt')
        if inputs['input_values'].shape != (1, count):
            raise ValueError('Frontend changed original waveform length')
        result.update(audio_sha256=args.audio_sha256, audio_duration_s=count / 16000., input_samples=count,
                      frontend_source_sha256=digest(sys.modules[extractor.__class__.__module__].__file__))
        model, loading = Wav2Vec2ForCTC.from_pretrained(model_root, local_files_only=True, use_safetensors=True,
                                                       low_cpu_mem_usage=True, torch_dtype=torch.float32,
                                                       attn_implementation='sdpa', output_loading_info=True)
        result['loading_info'] = loading
        result['weight_name_migration'] = repair_weight_names(model, loading, model_root)
        model.eval()
        result['runtime_model_source_sha256'] = digest(sys.modules[model.__class__.__module__].__file__)
        result['load_and_frontend_s'] = time.monotonic() - start
        arrays, heads = {}, {}
        for lang in LANGS:
            before = time.monotonic()
            model.load_adapter(lang, local_files_only=True, use_safetensors=True)
            if model.lm_head.out_features != len(vocabs[lang]):
                raise ValueError('Adapter head and publisher vocabulary disagree')
            with torch.inference_mode():
                logits = model(**inputs).logits[0].float()
                lp = torch.log_softmax(logits, dim=-1).cpu().numpy()
            if not np.isfinite(lp).all():
                raise ValueError('Nonfinite acoustic head output')
            path = output.with_name(output.stem + '-' + lang + '.npz')
            with path.open('xb') as file:
                np.savez_compressed(file, log_probs=lp)
            head = {'adapter': lang, 'elapsed_s': time.monotonic() - before,
                    'retained_logits_sha256': digest(path), 'frames': len(lp),
                    **collapse(lp.argmax(axis=1).tolist(), vocabs[lang])}
            save(path.with_suffix('.json'), head)
            arrays[lang], heads[lang] = lp, head
            print(lang, head['raw_text'], flush=True)
        result['heads'] = heads
        del model, inputs
        result.update(decode_pair(arrays, vocabs), status='success')
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        result.update(elapsed_s=time.monotonic() - start,
                      peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
        save(output, result)
        print(json.dumps({k: v for k, v in result.items() if k not in ('variants', 'numeric_token_provenance', 'allowed_ids')}, ensure_ascii=False), flush=True)


def supervise(args, cell_script=None):
    path = Path(args.manifest)
    manifest = json.loads(path.read_text())
    root = Path(manifest['results_directory'])
    root.mkdir(mode=0o700, exist_ok=False)
    baseline = memory_snapshot()
    for clip in manifest['recordings']:
        output = root / (clip['id'] + '.json')
        command = [sys.executable, str(Path(cell_script or __file__).resolve()), 'cell', '--model', manifest['model'],
                   '--wav', clip['wav'], '--audio-sha256', clip['sha256'], '--output', str(output)]
        start, peak, reason, samples = time.monotonic(), 0, None, []
        env = dict(os.environ, OPENBLAS_NUM_THREADS='2', OMP_NUM_THREADS='2', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
        with output.with_suffix('.stdout').open('xb') as out, output.with_suffix('.stderr').open('xb') as err:
            proc = subprocess.Popen(['nice', '-n', '19', *command], stdout=out, stderr=err, env=env)
            try:
                while proc.poll() is None:
                    peak = max(peak, rss_bytes(proc.pid))
                    mem, sensor = memory_snapshot(), sensors()
                    sample = {'elapsed_s': time.monotonic() - start, 'rss_bytes': peak,
                              'available_bytes': mem['MemAvailable'],
                              'swap_growth_bytes': mem['swap_used'] - baseline['swap_used'], **sensor}
                    samples.append(sample)
                    if peak > LIMITS['rss_mib'] * 1048576: reason = 'rss_limit'
                    if mem['MemAvailable'] < LIMITS['available_mib'] * 1048576: reason = 'available_memory_floor'
                    if sample['swap_growth_bytes'] > LIMITS['swap_growth_mib'] * 1048576: reason = 'swap_limit'
                    if any(t >= LIMITS['temperature_c'] * 1000 for t in sensor['temperatures_millic'].values()): reason = 'thermal_limit'
                    if time.monotonic() - start > LIMITS['seconds']: reason = 'timeout'
                    if reason: break
                    time.sleep(.5)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try: proc.wait(timeout=5)
                    except subprocess.TimeoutExpired: proc.kill()
                code = proc.wait()
        receipt = {'exit_code': code, 'stop_reason': reason, 'elapsed_s': time.monotonic() - start,
                   'peak_rss_bytes': peak, 'samples': samples, 'command': command,
                   'manifest_sha256': digest(path), 'limits': LIMITS, 'limits_source': 'agent-selected method protection'}
        save(output.with_name(output.stem + '-supervisor.json'), receipt)
        print(clip['id'], json.dumps({k: v for k, v in receipt.items() if k not in ('samples', 'command')}), flush=True)
        if code or reason:
            raise RuntimeError('Failed cell retained; remaining cells untouched')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='mode', required=True)
    c = sub.add_parser('cell')
    for key in ('model', 'wav', 'audio-sha256', 'output'):
        c.add_argument('--' + key, required=True)
    p = sub.add_parser('pilot')
    p.add_argument('manifest')
    args = parser.parse_args()
    if args.mode == 'cell': cell(args)
    else: supervise(args)
