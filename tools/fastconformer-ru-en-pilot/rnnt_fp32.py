"""Original FP32 RNNT predictor/joint, using retained whole-audio encoder.

No encoder call, no LM, no transcript rewrite. Keep the original search settings.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import tarfile
import time

from ctc_lm import pilot
from decoder import ContextBias, decode
from mms_pair import digest, save
from run import Guard

ORIGINAL_SHA = '8f1ec32033bd905c1666a26f8315ab9d830bd7baefa2b3c5b20db99ed1c77581'


class OriginalDecoder:
    def __init__(self, archive):
        import torch
        self.torch = torch
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        if digest(archive) != ORIGINAL_SHA:
            raise ValueError('Original checkpoint changed')
        with tarfile.open(archive) as container:
            with container.extractfile('./model_weights.ckpt') as file:
                all_weights = torch.load(file, map_location='cpu', weights_only=True)
        self.weights = {k: v for k, v in all_weights.items() if k.startswith(('decoder.', 'joint.'))}
        del all_weights
        expected = {'decoder.prediction.embed.weight': (2561, 640),
                    'decoder.prediction.dec_rnn.lstm.weight_ih_l0': (2560, 640),
                    'decoder.prediction.dec_rnn.lstm.weight_hh_l0': (2560, 640),
                    'decoder.prediction.dec_rnn.lstm.bias_ih_l0': (2560,),
                    'decoder.prediction.dec_rnn.lstm.bias_hh_l0': (2560,),
                    'joint.enc.weight': (640, 512), 'joint.enc.bias': (640,),
                    'joint.pred.weight': (640, 640), 'joint.pred.bias': (640,),
                    'joint.joint_net.2.weight': (2561, 640), 'joint.joint_net.2.bias': (2561,)}
        if set(expected) != set(self.weights) or any(tuple(self.weights[k].shape) != shape or self.weights[k].dtype != torch.float32 for k, shape in expected.items()):
            raise ValueError('Unexpected original predictor/joint architecture')
        self.lstm = torch.nn.LSTM(640, 640, 1).eval()
        prefix = 'decoder.prediction.dec_rnn.lstm.'
        self.lstm.load_state_dict({k.removeprefix(prefix): v for k, v in self.weights.items() if k.startswith(prefix)}, strict=True)
        self.tensor_hashes = {k: hashlib.sha256(v.numpy().tobytes()).hexdigest() for k, v in self.weights.items()}
        self.predict_calls = self.join_calls = 0

    def initial_states(self):
        return self.torch.zeros(1, 1, 640), self.torch.zeros(1, 1, 640)

    def predict(self, token, states):
        torch = self.torch
        with torch.inference_mode():
            embedding = torch.nn.functional.embedding(torch.tensor([[token]]), self.weights['decoder.prediction.embed.weight'])
            prediction, states = self.lstm(embedding, states)
        self.predict_calls += 1
        return prediction.reshape(640), states

    def join(self, encoded_frame, prediction):
        torch, w = self.torch, self.weights
        with torch.inference_mode():
            linear = torch.nn.functional.linear
            encoder = torch.from_numpy(encoded_frame.reshape(512))
            summed = linear(encoder, w['joint.enc.weight'], w['joint.enc.bias']) + linear(prediction, w['joint.pred.weight'], w['joint.pred.bias'])
            logits = linear(torch.relu(summed), w['joint.joint_net.2.weight'], w['joint.joint_net.2.bias'])
        self.join_calls += 1
        return logits.numpy()


def cell(args):
    import numpy as np
    output, root = Path(args.output), Path(args.root)
    if output.exists():
        raise FileExistsError('Consumed FP32 decoder cell')
    started = time.monotonic()
    guard = Guard(600, 4096)
    result = {'status': 'failed', 'encoder_rerun': False, 'waveform_input': False,
              'decoder_precision': 'original FP32', 'encoder_precision': 'retained published int8',
              'postprocessing': 'none', 'parameters': {'beam': 4, 'max_symbols': 10, 'context_scores': [0, 1.5], 'threads': 2},
              'source_commit': subprocess.check_output(['git', '-C', str(Path(__file__).parent), 'rev-parse', 'HEAD'], text=True).strip(),
              'host': os.uname().nodename, 'variants': {}}
    model = None
    try:
        receipt = json.loads(Path(args.receipt).read_text())
        saved = Path(args.receipt).with_suffix('.npz')
        if digest(saved) != receipt['retained_encoder_sha256']:
            raise ValueError('Retained encoder changed')
        with np.load(saved) as file:
            encoded, length = file['encoded'], int(file['length'][0])
        if encoded.ndim != 3 or encoded.shape[:2] != (1, 512) or length != receipt['encoded_frames'] or not 0 < length <= encoded.shape[2] or not np.isfinite(encoded).all():
            raise ValueError('Invalid retained encoder shape/length')
        artifacts = json.loads((root / 'fastconformer-pilot/prepared-artifacts.json').read_text())
        token_path = root / 'fastconformer-pilot/int8/tokens.txt'
        if digest(token_path) != artifacts['files_sha256']['tokens.txt']:
            raise ValueError('Original token map changed')
        pieces = {int(line.rsplit(' ', 1)[1]): line.rsplit(' ', 1)[0] for line in token_path.read_text().splitlines()}
        context_receipt = json.loads(Path(args.context_receipt).read_text())
        if context_receipt['original_audio_sha256'] != receipt['audio_sha256']:
            raise ValueError('Mismatched original audio provenance')
        hint_paths = context_receipt['variants']['context']['context_paths']
        paths = [p['token_ids'] for p in hint_paths]
        model = OriginalDecoder(Path(args.model))
        guard.check()
        result.update(audio_sha256=receipt['audio_sha256'], original_checkpoint_sha256=ORIGINAL_SHA,
                      parent_receipt_sha256=digest(args.receipt), context_receipt_sha256=digest(args.context_receipt),
                      retained_encoder_sha256=digest(saved), tensor_hashes=model.tensor_hashes,
                      load_s=time.monotonic() - started, allowed_token_ids=artifacts['allowed_token_ids'], blank_id=2560)
        for name, score in (('no-hints', 0.0), ('context', 1.5)):
            before = time.monotonic()
            value = decode(model, encoded, length, artifacts['allowed_token_ids'], 2560,
                           ContextBias(paths if score else (), score), beam=4, max_symbols=10, check=guard.check)
            ids = value['token_ids']
            if any(t not in artifacts['allowed_token_ids'] for t in ids):
                raise ValueError('Forbidden numerical ID emitted')
            value.update(raw_text=''.join(pieces[t] for t in ids).replace('▁', ' ').strip(),
                         english_token_count=sum(512 <= t < 768 for t in ids),
                         russian_token_count=sum(1280 <= t < 1536 for t in ids),
                         decode_s=time.monotonic() - before, context_score=score,
                         context_paths=hint_paths if score else [])
            value['postprocessed_text'] = value['raw_text']
            save(output.with_name(output.stem + '-' + name + '.json'), value)
            result['variants'][name] = value
            print(name, value['raw_text'], flush=True)
        result['status'] = 'success'
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        result.update(elapsed_s=time.monotonic() - started,
                      peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                      guard=guard.receipt())
        if model:
            result['calls'] = {'predictor': model.predict_calls, 'joiner': model.join_calls}
        save(output, result)
        print(json.dumps({k: v for k, v in result.items() if k not in ('variants', 'allowed_token_ids', 'tensor_hashes')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='mode', required=True)
    c = sub.add_parser('cell')
    for key in ('root', 'model', 'receipt', 'context-receipt', 'output'):
        c.add_argument('--' + key, required=True)
    p = sub.add_parser('pilot')
    p.add_argument('manifest')
    args = parser.parse_args()
    if args.mode == 'cell': cell(args)
    else: pilot(args, cell_script=__file__)
