"""Whole-audio code-switch fine-tune quality diagnostic, NOT a hard pair decoder.

Uses CT2 directly to avoid VAD, segmentation, resampling or pad-to-30-seconds.
The selected model still has a shared multilingual vocabulary. Language prompts
and hints are conditioning only, never claimed to enforce RU/EN-only output.
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

from run import digest, memory_snapshot, sensors
from pilot import rss_bytes

REV = 'bf64d2a976a268e35041f74233f889f951f0f676'


def cell(args):
    output = Path(args.output)
    if output.exists(): raise FileExistsError('Consumed cell')
    started = time.monotonic()
    result = {'status': 'failed', 'parameters': vars(args), 'model_revision': REV,
              'source_commit': subprocess.check_output(['git', '-C', str(Path(__file__).parent), 'rev-parse', 'HEAD'], text=True).strip(),
              'strict_language_pair': False, 'segmentation': False, 'audio_padding': False,
              'postprocessing': 'none', 'host': os.uname().nodename,
              'runtime_versions': {x: importlib.metadata.version(x) for x in ('faster-whisper', 'ctranslate2', 'tokenizers', 'numpy')}}
    try:
        import numpy as np
        import ctranslate2
        from faster_whisper.feature_extractor import FeatureExtractor
        from tokenizers import Tokenizer
        root = Path(args.model)
        receipt = json.loads((root / 'download-receipt.json').read_text())
        if receipt['revision'] != REV: raise ValueError('Wrong model revision')
        for item in receipt['files']:
            if digest(root / item['name']) != item['sha256']:
                raise ValueError('Model changed: ' + item['name'])
        result['asset_receipt_sha256'] = digest(root / 'download-receipt.json')
        if digest(args.wav) != args.audio_sha256: raise ValueError('Audio changed')
        with wave.open(args.wav, 'rb') as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
                raise ValueError('Whole original PCM16 mono16k required')
            n = wav.getnframes()
            audio = np.frombuffer(wav.readframes(n), dtype='<i2').astype(np.float32) / 32768
        if len(audio) != n or n > 30 * 16000: raise ValueError('Unsupported audio length')
        config = json.loads((root / 'preprocessor_config.json').read_text())
        frontend = FeatureExtractor(feature_size=config['feature_size'])
        features = frontend(audio, padding=0)
        result.update(audio_duration_s=n / 16000, audio_sha256=args.audio_sha256,
                      feature_frames=features.shape[-1], model_native_feature_padding=False,
                      feature_source_sha256=digest(sys.modules[FeatureExtractor.__module__].__file__))
        model = ctranslate2.models.Whisper(str(root), device='cpu', compute_type='int8',
                                           intra_threads=2, inter_threads=1)
        tokenizer = Tokenizer.from_file(str(root / 'tokenizer.json'))
        encoded = model.encode(ctranslate2.StorageView.from_array(features[None]))
        encoding_complete = time.monotonic()
        result['load_features_encode_s'] = encoding_complete - started
        result['compute_type'] = model.compute_type
        base = [tokenizer.token_to_id(t) for t in ('<|startoftranscript|>', '<|ru|>', '<|transcribe|>', '<|notimestamps|>')]
        if any(t is None for t in base): raise ValueError('Missing task tokens')
        variants = {}
        for name, hint in (('no-hints', ''), ('name-context', 'ChatGPT, ChatGPT Pro, DSH, Oracle.')):
            prompt = list(base)
            if hint:
                prompt = [tokenizer.token_to_id('<|startofprev|>'), *tokenizer.encode(' ' + hint, add_special_tokens=False).ids, *base]
            before = time.monotonic()
            out = model.generate(encoded, [prompt], beam_size=5, num_hypotheses=3,
                                 max_length=448, return_scores=True, return_no_speech_prob=True,
                                 sampling_temperature=0, suppress_blank=True, suppress_tokens=[-1])[0]
            hypotheses = [{'raw_text': tokenizer.decode(ids, skip_special_tokens=True),
                           'postprocessed_text': tokenizer.decode(ids, skip_special_tokens=True),
                           'token_ids': ids, 'score': score} for ids, score in zip(out.sequences_ids, out.scores)]
            variants[name] = {'prompt_text': hint, 'prompt_ids': prompt, 'beam': 5,
                              'decode_s': time.monotonic() - before,
                              'no_speech_prob': out.no_speech_prob, 'hypotheses': hypotheses}
            result['variants'] = variants
            # Persist a finished decoder variant even if the later one is killed.
            with output.with_name(output.stem + '-' + name + '.json').open('x') as file:
                json.dump(variants[name], file, ensure_ascii=False, indent=2)
            print(name, hypotheses[0]['raw_text'], flush=True)
        result['status'] = 'success'
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        result.update(elapsed_s=time.monotonic() - started,
                      peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
        with output.open('x') as file:
            json.dump(result, file, ensure_ascii=False, indent=2)
        print(json.dumps({k: v for k, v in result.items() if k != 'variants'}, ensure_ascii=False), flush=True)


def supervise(args):
    manifest_path = Path(args.manifest)
    manifest = json.loads(manifest_path.read_text())
    results = Path(manifest['results_directory'])
    results.mkdir(mode=0o700, exist_ok=False)
    baseline = memory_snapshot()
    for clip in manifest['recordings']:
        output = results / (clip['id'] + '.json')
        cmd = [sys.executable, str(Path(__file__).resolve()), 'cell', '--model', manifest['model'],
               '--wav', clip['wav'], '--audio-sha256', clip['sha256'], '--output', str(output)]
        started, peak, reason, samples = time.monotonic(), 0, None, []
        with output.with_suffix('.stdout').open('xb') as out, output.with_suffix('.stderr').open('xb') as err:
            proc = subprocess.Popen(['nice', '-n', '19', *cmd], stdout=out, stderr=err,
                                    env=dict(os.environ, OPENBLAS_NUM_THREADS='2', OMP_NUM_THREADS='2'))
            try:
                while proc.poll() is None:
                    peak = max(peak, rss_bytes(proc.pid))
                    mem, sensor = memory_snapshot(), sensors()
                    sample = {'elapsed_s': time.monotonic() - started, 'rss_bytes': peak,
                              'available_bytes': mem['MemAvailable'],
                              'swap_growth_bytes': mem['swap_used'] - baseline['swap_used'], **sensor}
                    samples.append(sample)
                    if peak > 4096 * 1048576: reason = 'rss_limit'
                    if mem['MemAvailable'] < 2048 * 1048576: reason = 'available_memory_floor'
                    if sample['swap_growth_bytes'] > 256 * 1048576: reason = 'swap_limit'
                    if any(x >= 85000 for x in sensor['temperatures_millic'].values()): reason = 'thermal_limit'
                    if time.monotonic() - started > 240: reason = 'timeout'
                    if reason: break
                    time.sleep(.5)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try: proc.wait(timeout=5)
                    except subprocess.TimeoutExpired: proc.kill()
                code = proc.wait()
        receipt = {'exit_code': code, 'stop_reason': reason, 'elapsed_s': time.monotonic() - started,
                   'peak_rss_bytes': peak, 'samples': samples, 'command': cmd,
                   'manifest_sha256': digest(manifest_path)}
        with output.with_name(output.stem + '-supervisor.json').open('x') as file:
            json.dump(receipt, file, indent=2)
        print(clip['id'], json.dumps({k: v for k, v in receipt.items() if k not in ('samples', 'command')}), flush=True)
        if code or reason: raise RuntimeError('Failed/stopped cell retained; untouched cells not consumed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='mode', required=True)
    c = sub.add_parser('cell')
    for name in ('model', 'wav', 'audio-sha256', 'output'): c.add_argument('--' + name, required=True)
    p = sub.add_parser('pilot')
    p.add_argument('manifest')
    args = parser.parse_args()
    if args.mode == 'cell': cell(args)
    else: supervise(args)
