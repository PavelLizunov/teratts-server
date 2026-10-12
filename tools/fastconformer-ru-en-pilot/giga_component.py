"""Whole-recording GigaAM-v3 Russian component with official 320sample frontend.

This is not a bilingual recognizer. Preserve native40ms outputs; no interpolation
or unproven fusion with the20ms English specialist. No VAD/padding/resampling.
"""
import argparse
import importlib.metadata
import json
from pathlib import Path
import resource
import subprocess
import sys
import time
import wave

from mms_pair import digest, save, supervise
from run import Guard

REV = '32a4c7cc81809bd132e2d935ab99e9e6ab47fbec'
FRONTEND = {'sample_rate': 16000, 'n_mels': 64, 'win_length': 320,
            'hop_length': 160, 'n_fft': 320, 'center': False,
            'power': 2.0, 'normalized': False, 'norm': None, 'mel_scale': 'htk'}


def cell(args):
    import numpy as np
    import torch
    import torchaudio
    import onnxruntime as ort
    output, root = Path(args.output), Path(args.model)
    if output.exists() or output.with_suffix('.npz').exists():
        raise FileExistsError('Consumed or unknown Russian component pass')
    started = time.monotonic()
    guard = Guard(600, 8192)
    result = {'status': 'failed', 'language': 'Russian', 'bilingual': False,
              'source_commit': subprocess.check_output(['git', '-C', str(Path(__file__).parent), 'rev-parse', 'HEAD'], text=True).strip(),
              'segmentation': False, 'audio_padding': False, 'postprocessing': 'none',
              'frontend': FRONTEND, 'variants': {}}
    try:
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        receipt = json.loads((root / 'download-receipt.json').read_text())
        if receipt['revision'] != REV:
            raise ValueError('Wrong pinned GigaAM export')
        for row in receipt['files']:
            if digest(root / row['name']) != row['sha256']:
                raise ValueError('Changed model artifact')
        if digest(args.wav) != args.audio_sha256:
            raise ValueError('Original waveform changed')
        with wave.open(args.wav, 'rb') as file:
            if (file.getnchannels(), file.getsampwidth(), file.getframerate(), file.getcomptype()) != (1, 2, 16000, 'NONE'):
                raise ValueError('Original PCM16mono16k required')
            count = file.getnframes()
            waveform = torch.from_numpy(np.frombuffer(file.readframes(count), dtype='<i2').astype(np.float32) / 32768.)[None]
        frontend = torchaudio.transforms.MelSpectrogram(**FRONTEND)
        with torch.inference_mode():
            features = frontend(waveform).clamp(1e-9, 1e9).log()
        expected_frames = (count - 320) // 160 + 1
        if tuple(features.shape) != (1, 64, expected_frames):
            raise ValueError('Official no-padding frontend length mismatch')
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        opts.inter_op_num_threads = 1
        model = ort.InferenceSession(str(root / 'model.int8.onnx'), sess_options=opts, providers=['CPUExecutionProvider'])
        metadata = model.get_modelmeta().custom_metadata_map
        if metadata.get('is_giga_am') != '1' or metadata.get('comment') != 'v3' or metadata.get('language') != 'Russian':
            raise ValueError('Wrong exported acoustic model')
        guard.check()
        before = time.monotonic()
        values = model.run(None, {model.get_inputs()[0].name: features.numpy(),
                                 model.get_inputs()[1].name: np.array([expected_frames], np.int64)})[0][0]
        guard.check()
        if values.ndim != 2 or values.shape[1] != 34 or not np.isfinite(values).all():
            raise ValueError('Invalid native Russian output')
        log_normalizer = np.logaddexp.reduce(values.astype(np.float64), axis=1)
        if np.abs(log_normalizer).max() > .001:
            raise ValueError('Expected published log probabilities')
        with output.with_suffix('.npz').open('xb') as file:
            np.savez_compressed(file, log_probs=values)
        tokens = {}
        for line in (root / 'tokens.txt').read_text().splitlines():
            piece, index = line.rsplit(' ', 1)
            tokens[int(index)] = piece
        if len(tokens) != 34 or tokens[0] != ' ' or tokens[33] != '<blk>':
            raise ValueError('Unexpected trained token map')
        path = values.argmax(-1).tolist()
        ids, previous = [], None
        for token in path:
            if token != previous and token != 33:
                ids.append(token)
            previous = token
        text = ''.join(tokens[t] for t in ids)
        result.update(status='success', raw_text=text, token_ids=ids, postprocessed_text=text,
                      audio_sha256=args.audio_sha256, audio_duration_s=count/16000.,
                      feature_frames=expected_frames, native_output_frames=len(values),
                      native_frame_stride_s=.04, exact_frame_center_geometry='not yet derived for cross-model fusion',
                      logsoftmax_normalization_max_error=float(np.abs(log_normalizer).max()),
                      retained_logits_sha256=digest(output.with_suffix('.npz')),
                      model_metadata=metadata, model_signature={'inputs': [str(x) for x in model.get_inputs()], 'outputs': [str(x) for x in model.get_outputs()]},
                      asset_receipt_sha256=digest(root / 'download-receipt.json'), forward_s=time.monotonic()-before,
                      frontend_source_sha256=digest(sys.modules[frontend.__class__.__module__].__file__),
                      runtime_versions={k: importlib.metadata.version(k) for k in ('torch', 'torchaudio', 'onnxruntime', 'numpy')})
        print(text, flush=True)
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        result.update(elapsed_s=time.monotonic()-started, peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                      guard=guard.receipt())
        save(output, result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='mode', required=True)
    c = sub.add_parser('cell')
    for key in ('model', 'wav', 'audio-sha256', 'output'):
        c.add_argument('--'+key, required=True)
    p = sub.add_parser('pilot')
    p.add_argument('manifest')
    args = parser.parse_args()
    if args.mode == 'cell': cell(args)
    else: supervise(args, cell_script=__file__)
