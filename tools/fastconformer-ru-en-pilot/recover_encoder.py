"""Recover original encoder activations from full-rank retained CTC logprobs.

Subtract the classwise mean to remove the log-softmax normalizer. Solve the
known affine projection in double precision. No waveform or encoder forward.
"""
import argparse
import json
from pathlib import Path
import subprocess

from mms_pair import digest, save

MODEL_SHA = 'b0e77792202b0113e8439b5cff88e24119016f861425940a45f57568137dec4b'


def main(args):
    import torch
    import onnx
    import numpy as np
    from onnx import numpy_helper
    torch.set_num_threads(2)
    root, destination = Path(args.root), Path(args.output)
    destination.mkdir(mode=0o700, exist_ok=False)
    path = root / 'alternative-methods/ctc-fp32/model.onnx'
    if digest(path) != MODEL_SHA:
        raise ValueError('Original CTC export changed')
    model = onnx.load(path)
    tensors = {v.name: numpy_helper.to_array(v).copy() for v in model.graph.initializer if v.name.startswith('ctc_decoder.')}
    weight = torch.from_numpy(tensors['ctc_decoder.decoder_layers.0.weight']).squeeze(-1).double()
    bias = torch.from_numpy(tensors['ctc_decoder.decoder_layers.0.bias']).double()
    matrix = weight - weight.mean(0, keepdim=True)
    singular = torch.linalg.svdvals(matrix)
    if float(singular[-1]) < 1e-6:
        raise ValueError('CTC projection does not uniquely identify encoder')
    for clip in ('short', 'long'):
        parent = root / f'alternative-methods/results-ctc-fp32-v1/{clip}-ctc-fp32-nemo.json'
        receipt = json.loads(parent.read_text())
        if digest(parent.with_suffix('.npz')) != receipt['retained_logits_sha256']:
            raise ValueError('Retained CTC logits changed')
        with np.load(parent.with_suffix('.npz')) as file:
            logp = torch.from_numpy(file['log_probs']).double()
        y = logp - bias
        y -= y.mean(1, keepdim=True)
        recovered = torch.linalg.lstsq(matrix, y.T, driver='gelsd')
        if int(recovered.rank) != 512:
            raise ValueError('Incomplete recovered encoder rank')
        hidden = recovered.solution.T
        reprojection = (hidden @ weight.T + bias).log_softmax(-1)
        error = reprojection - logp
        if float(error.abs().max()) > .001:
            raise ValueError('Excessive recovered projection residual')
        encoded = hidden.float().T[None].contiguous().numpy()
        old_path = root / f'alternative-methods/results-rnnt-nemo-v1/{clip}-no-bias.json'
        old = json.loads(old_path.read_text())
        if old['audio_sha256'] != receipt['audio_sha256'] or digest(old_path.with_suffix('.npz')) != old['retained_encoder_sha256']:
            raise ValueError('Inconsistent original recording provenance')
        with np.load(old_path.with_suffix('.npz')) as file:
            old_encoded = file['encoded']
        if old_encoded.shape != encoded.shape:
            raise ValueError('Encoder frame shape differs')
        delta = encoded.astype(np.float64) - old_encoded
        out = destination / (clip + '.json')
        with out.with_suffix('.npz').open('xb') as file:
            np.savez_compressed(file, encoded=encoded, length=np.array([len(logp)]))
        result = {'status': 'success', 'encoder_precision': 'FP32 numerically recovered from retained CTC logprobs',
                  'audio_sha256': receipt['audio_sha256'], 'encoded_frames': len(logp),
                  'retained_encoder_sha256': digest(out.with_suffix('.npz')),
                  'parent_receipt_sha256': digest(parent), 'ctc_export_sha256': MODEL_SHA,
                  'source_commit': subprocess.check_output(['git', '-C', str(Path(__file__).parent), 'rev-parse', 'HEAD'], text=True).strip(),
                  'encoder_rerun': False, 'waveform_input': False, 'projection_rank': int(recovered.rank),
                  'projection_condition': float(singular[0] / singular[-1]),
                  'reprojected_logsoftmax_max_error': float(error.abs().max()),
                  'reprojected_logsoftmax_rms_error': float(error.square().mean().sqrt()),
                  'int8_encoder_difference_max': float(np.abs(delta).max()),
                  'int8_encoder_difference_rms': float(np.sqrt((delta * delta).mean())),
                  'numerically_recovered_not_bit_identical': True}
        save(out, result)
        print(clip, json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--output', required=True)
    main(parser.parse_args())
