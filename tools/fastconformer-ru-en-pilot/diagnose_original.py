"""Diagnose original checkpoint frontend buffers and FP32 ONNX correspondence.

No acoustic model execution, no synthetic inputs, no transcript scoring. The
original checkpoint is read through weights_only=True, never pickle fallback.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import wave

from frontend import nemo_features
from mms_pair import digest, save

ORIGINAL_SHA = '8f1ec32033bd905c1666a26f8315ab9d830bd7baefa2b3c5b20db99ed1c77581'
ONNX_SHA = 'b0e77792202b0113e8439b5cff88e24119016f861425940a45f57568137dec4b'
AUDIO = {'short': ('chatgpt-pro-original.wav', 'f8b7da4ac0335095e9e8542bf25e1f4191d930fa8b2fb662bcb1840fdb1e8d7a'),
         'long': ('original.wav', '8d9314f71c42f554d0a26f5e7da9fb5ea72f1e451272e1c5bb014a019bc5ea50')}


def main(args):
    import numpy as np
    import torch
    import onnx
    from onnx import numpy_helper
    torch.set_num_threads(2)
    root, out = Path(args.root), Path(args.output)
    if out.exists() or out.with_suffix('.npz').exists():
        raise FileExistsError('Preserve prior diagnostic')
    checkpoint = root / 'fastconformer-pilot/original-1.21.0.nemo'
    export = root / 'alternative-methods/ctc-fp32/model.onnx'
    if digest(checkpoint) != ORIGINAL_SHA or digest(export) != ONNX_SHA:
        raise ValueError('Original or export asset changed')
    with tarfile.open(checkpoint) as archive:
        with archive.extractfile('./model_weights.ckpt') as file:
            weights = torch.load(file, map_location='cpu', weights_only=True)
    window = weights['preprocessor.featurizer.window']
    bank = weights['preprocessor.featurizer.fb']
    config = json.loads((root / 'fastconformer-pilot/prepared-artifacts.json').read_text())['preprocessor']
    result = {'source_commit': subprocess.check_output(['git', '-C', str(Path(__file__).parent), 'rev-parse', 'HEAD'], text=True).strip(),
              'original_sha256': ORIGINAL_SHA, 'export_sha256': ONNX_SHA, 'model_executed': False,
              'torch': torch.__version__, 'onnx': onnx.__version__, 'numpy': np.__version__,
              'original_window_vs_torch_hann_max_abs': float((window - torch.hann_window(400, periodic=False)).abs().max()),
              'frontend': {}}
    retained = {}
    for name, (filename, audio_sha) in AUDIO.items():
        path = root / filename
        if digest(path) != audio_sha:
            raise ValueError('Original audio changed')
        with wave.open(str(path), 'rb') as file:
            x = torch.from_numpy(np.frombuffer(file.readframes(file.getnframes()), dtype='<i2').copy().astype(np.float32)) / 32768.
        x = torch.cat((x[:1], x[1:] - .97 * x[:-1]))
        spectrum = torch.stft(x[None], n_fft=512, hop_length=160, win_length=400,
                              center=True, window=window, return_complex=True)
        power = torch.sqrt(torch.view_as_real(spectrum).pow(2).sum(-1)).pow(2)
        mel = torch.log(torch.matmul(bank, power) + 2 ** -24)
        feats = (mel - mel.mean(-1, keepdim=True)) / (mel.std(-1, keepdim=True) + 1e-5)
        expected = feats[0].T.contiguous().numpy()
        current, duration = nemo_features(path, config)
        if current.shape != expected.shape:
            raise ValueError('Frontend frame shape mismatch')
        delta = current.astype(np.float64) - expected
        result['frontend'][name] = {'audio_sha256': audio_sha, 'shape': list(current.shape),
                                    'rms_difference': float(np.sqrt(np.mean(delta ** 2))),
                                    'max_abs_difference': float(np.max(np.abs(delta))),
                                    'fraction_abs_over_1e3': float((np.abs(delta) > 1e-3).mean()),
                                    'current_sha256': hashlib.sha256(current.tobytes()).hexdigest(),
                                    'checkpoint_buffer_torch_sha256': hashlib.sha256(expected.tobytes()).hexdigest()}
        retained[name] = expected
    with out.with_suffix('.npz').open('xb') as file:
        np.savez_compressed(file, **retained)
    result['retained_torch_features_sha256'] = digest(out.with_suffix('.npz'))
    # Exporter may transpose linear weights or constant-fold batch norm. Exact
    # tensor matches prove only corresponding parameters, never full equivalence.
    originals = {}
    for name, tensor in weights.items():
        if not hasattr(tensor, 'numpy'):
            continue
        array = tensor.numpy()
        for operation, candidate in [('identity', array), ('squeeze', array.squeeze())] + ([('transpose', array.T)] if array.ndim == 2 else []):
            key = (tuple(candidate.shape), str(candidate.dtype), hashlib.sha256(candidate.tobytes()).hexdigest())
            originals.setdefault(key, []).append({'name': name, 'operation': operation})
    model = onnx.load(export)
    rows = []
    for tensor in model.graph.initializer:
        a = numpy_helper.to_array(tensor)
        key = (tuple(a.shape), str(a.dtype), hashlib.sha256(a.tobytes()).hexdigest())
        rows.append({'export_name': tensor.name, 'shape': list(a.shape), 'elements': int(a.size),
                     'exact_original_matches': originals.get(key, [])})
    result['onnx_initializers'] = rows
    result['exact_match_summary'] = {'matched_tensors': sum(bool(x['exact_original_matches']) for x in rows),
                                     'total_tensors': len(rows),
                                     'matched_elements': sum(x['elements'] for x in rows if x['exact_original_matches']),
                                     'total_elements': sum(x['elements'] for x in rows)}
    result['limitation'] = 'Unmatched may be folded constants; matched weights do not prove ONNX operator parity. No ASR rerun.'
    save(out, result)
    print(json.dumps({k: v for k, v in result.items() if k != 'onnx_initializers'}, ensure_ascii=False), flush=True)
    print('unmatched', json.dumps([x for x in rows if not x['exact_original_matches']], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--output', required=True)
    main(parser.parse_args())
