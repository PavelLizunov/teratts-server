"""Inspect RNNT internal language distribution along retained historical paths.

No new transcription/encoder pass: remove the FULL projected acoustic term,
including its bias, from a task-local graph copy. ILME eq21–26, arXiv2011.01991.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time

from mms_pair import digest, save


def main(args):
    import numpy as np
    import onnx
    from onnx import helper
    import onnxruntime as ort
    root, output = Path(args.root), Path(args.output)
    if output.exists() or output.with_suffix('.onnx').exists():
        raise FileExistsError('Preserve existing diagnostic')
    start = time.monotonic()
    artifacts = json.loads((root / 'fastconformer-pilot/prepared-artifacts.json').read_text())
    model_root = root / 'fastconformer-pilot/int8'
    for name in ('decoder.int8.onnx', 'joiner.int8.onnx'):
        if digest(model_root / name) != artifacts['files_sha256'][name]:
            raise ValueError('Retained predictor/joiner changed')
    graph = onnx.load(model_root / 'joiner.int8.onnx')
    merge = [n for n in graph.graph.node if n.name == '/Add']
    if len(merge) != 1 or list(merge[0].input) != ['/Unsqueeze_output_0', '/Unsqueeze_1_output_0']:
        raise ValueError('Unexpected joint merge graph')
    nodes = [helper.make_node('Identity', ['/Unsqueeze_1_output_0'], list(n.output), name='task_ilm_remove_projected_acoustics')
             if n.name == '/Add' else n for n in graph.graph.node]
    needed = {x.name for x in graph.graph.output}
    keep = []
    for n in reversed(nodes):
        if any(x in needed for x in n.output):
            keep.append(n)
            needed.update(n.input)
    del graph.graph.node[:]
    graph.graph.node.extend(reversed(keep))
    inputs = [x for x in graph.graph.input if x.name in needed]
    tensors = [x for x in graph.graph.initializer if x.name in needed]
    del graph.graph.input[:]
    graph.graph.input.extend(inputs)
    del graph.graph.initializer[:]
    graph.graph.initializer.extend(tensors)
    if [x.name for x in graph.graph.input] != ['decoder_outputs'] or any(x.name == 'enc.bias' for x in graph.graph.initializer):
        raise ValueError('Acoustic contribution was not fully removed')
    onnx.save(graph, output.with_suffix('.onnx'))
    options = ort.SessionOptions()
    options.inter_op_num_threads = options.intra_op_num_threads = 1
    def session(path):
        return ort.InferenceSession(str(path), sess_options=options, providers=['CPUExecutionProvider'])
    predictor, joiner, ilm = (session(p) for p in (model_root / 'decoder.int8.onnx', model_root / 'joiner.int8.onnx', output.with_suffix('.onnx')))
    blank = artifacts['blank_id']
    branches = [np.arange(artifacts['languages'][l]['offset'], artifacts['languages'][l]['offset'] + artifacts['languages'][l]['size']) for l in ('en', 'ru')]
    def stats(logits):
        logits = np.asarray(logits, dtype=np.float64).reshape(-1)
        normalizer = np.logaddexp.reduce(logits[:blank])
        lp = logits[:blank] - normalizer
        masses = [float(np.exp(lp[ids]).sum()) for ids in branches]
        return {'en_pair_fraction': masses[0] / sum(masses), 'en_nonblank_mass': masses[0],
                'ru_nonblank_mass': masses[1], 'top_nonblank_id': int(lp.argmax())}
    rows = []
    for clip in ('short', 'long'):
        path = root / f'alternative-methods/results-rnnt-nemo-v1/{clip}-no-bias.json'
        receipt = json.loads(path.read_text())
        if digest(path.with_suffix('.npz')) != receipt['retained_encoder_sha256']:
            raise ValueError('Retained encoder changed')
        with np.load(path.with_suffix('.npz')) as file:
            encoded, length = file['encoded'], int(file['length'][0])
        states = (np.zeros((1, 1, 640), dtype=np.float32), np.zeros((1, 1, 640), dtype=np.float32))
        previous, steps = blank, []
        for token, frame in zip(receipt['token_ids'], receipt['frame_indices']):
            if not 0 <= frame < length:
                raise ValueError('Historical frame outside retained encoder')
            values = [np.array([[previous]], dtype=np.int32), np.array([1], dtype=np.int32), *states]
            pred = predictor.run(None, {x.name: v for x, v in zip(predictor.get_inputs(), values)})
            states = pred[2], pred[3]
            ordinary = joiner.run(None, {'encoder_outputs': encoded[:, :, frame:frame+1], 'decoder_outputs': pred[0]})[0]
            internal = ilm.run(None, {'decoder_outputs': pred[0]})[0]
            steps.append({'emitted_id': token, 'emission_frame': frame, 'ordinary_joint': stats(ordinary), 'internal_lm': stats(internal)})
            previous = token
        summary = {}
        for source in ('ordinary_joint', 'internal_lm'):
            en = np.array([s[source]['en_pair_fraction'] for s in steps])
            summary[source] = {'min_en': float(en.min()), 'median_en': float(np.median(en)),
                               'max_en': float(en.max()), 'mean_en': float(en.mean()),
                               'en_dominant_steps': int((en > .5).sum()), 'total_steps': len(en)}
        rows.append({'clip': clip, 'parent_receipt_sha256': digest(path), 'summary': summary, 'steps': steps})
        print(clip, json.dumps(summary), flush=True)
    save(output, {'source_commit': subprocess.check_output(['git', '-C', str(Path(__file__).parent), 'rev-parse', 'HEAD'], text=True).strip(),
                  'method_source': 'https://arxiv.org/html/2011.01991', 'model_weights_changed': False,
                  'new_transcript': False, 'encoder_rerun': False, 'audio_input': False,
                  'removed': 'projected_encoder_and_encoder_bias', 'elapsed_s': time.monotonic() - start,
                  'derived_graph_sha256': digest(output.with_suffix('.onnx')), 'recordings': rows,
                  'limitation': 'Conditional on historical RU-dominated token paths; not independent LID or proof of correct alternatives'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--output', required=True)
    main(parser.parse_args())
