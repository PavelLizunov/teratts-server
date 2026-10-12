"""Two monolingually trained CTC specialists, whole-audio head-state search.

Both have the same trained convolution frame geometry; there is no cropping,
padding, interpolation, LID oracle or transcript rewriting. Cross-head scores
are not calibrated. Preserve raw heads to avoid repeated acoustic passes.
"""
import argparse
import gc
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import wave

from mms_pair import LANGS, LIMITS, collapse, digest, save, supervise
from mms_word_graph import search
from run import Guard

MODELS = {'eng': ('facebook/wav2vec2-large-960h-lv60-self', '54074b1c16f4de6a5ad59affb4caa8f2ea03a119', 32),
          'rus': ('bond005/wav2vec2-large-ru-golos', 'c361ee1f5bd6589ac7abe8f5bb6d136561339cb0', 37)}


def load_strict(root):
    import torch
    from accelerate import init_empty_weights
    from transformers import Wav2Vec2Config, Wav2Vec2ForCTC
    weights = torch.load(root / 'pytorch_model.bin', map_location='cpu', weights_only=True)
    config = Wav2Vec2Config.from_pretrained(root, local_files_only=True)
    if (config.conv_kernel != [10, 3, 3, 3, 3, 2, 2] or config.conv_stride != [5, 2, 2, 2, 2, 2, 2]
            or config.pad_token_id != 0 or config.num_hidden_layers != 24 or config.hidden_size != 1024):
        raise ValueError('Unexpected specialist architecture/time geometry')
    config._attn_implementation = 'sdpa'
    # Old inference checkpoints may omit this training-only SpecAugment vector.
    # Do not invent a random parameter: disable the unreachable training branch.
    missing_training_mask = 'wav2vec2.masked_spec_embed' not in weights
    if missing_training_mask:
        config.mask_time_prob = config.mask_feature_prob = 0.0
    config.apply_spec_augment = False
    with init_empty_weights():
        model = Wav2Vec2ForCTC(config)
    target = model.state_dict()
    prefix = 'wav2vec2.encoder.pos_conv_embed.conv.'
    mapping = {prefix + 'weight_g': prefix + 'parametrizations.weight.original0',
               prefix + 'weight_v': prefix + 'parametrizations.weight.original1'}
    used = {}
    for old, new in mapping.items():
        if old in weights and new in target and new not in weights:
            weights[new] = weights.pop(old)
            used[old] = new
    if set(weights) != set(target):
        raise ValueError('Unexpected missing/extra weights: ' + repr((sorted(set(target)-set(weights)), sorted(set(weights)-set(target)))))
    model.load_state_dict(weights, strict=True, assign=True)
    actual = model.state_dict()
    if any(not torch.equal(actual[k], v) for k, v in weights.items()):
        raise ValueError('Strict loader altered model tensors')
    del weights
    model.eval()
    return model, {'mapping': used, 'all_tensor_values_equal': True, 'missing_keys': [], 'unexpected_keys': [],
                   'absent_training_only_mask_not_constructed': missing_training_mask,
                   'spec_augment': False, 'model_training': model.training}


def cell(args):
    output, root = Path(args.output), Path(args.model)
    if output.exists() or any(output.with_name(output.stem + '-' + lang + '.npz').exists() for lang in LANGS):
        raise FileExistsError('Consumed or unknown-outcome acoustic cell')
    started = time.monotonic()
    guard = Guard(LIMITS['seconds'], LIMITS['rss_mib'])
    result = {'status': 'failed', 'heads': {}, 'variants': {}, 'allowed_trained_heads': list(LANGS),
              'semantic_language_guarantee': False, 'calibrated_language_detection': False,
              'segmentation': False, 'audio_padding': False, 'postprocessing': 'none',
              'source_commit': subprocess.check_output(['git', '-C', str(Path(__file__).parent), 'rev-parse', 'HEAD'], text=True).strip(),
              'host': os.uname().nodename}
    try:
        import numpy as np
        import torch
        from transformers import Wav2Vec2FeatureExtractor
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        result['runtime_versions'] = {k: importlib.metadata.version(k) for k in ('torch', 'transformers', 'accelerate', 'numpy')}
        if digest(args.wav) != args.audio_sha256:
            raise ValueError('Original audio changed')
        with wave.open(args.wav, 'rb') as file:
            if (file.getnchannels(), file.getsampwidth(), file.getframerate(), file.getcomptype()) != (1, 2, 16000, 'NONE'):
                raise ValueError('Original unmodified mono PCM16 16k WAV required')
            count = file.getnframes()
            audio = np.frombuffer(file.readframes(count), dtype='<i2').astype(np.float32) / 32768
        result.update(audio_sha256=args.audio_sha256, audio_duration_s=count / 16000, input_samples=count)
        arrays, vocabs = {}, {}
        for lang in LANGS:
            before = time.monotonic()
            folder = root / lang
            receipt = json.loads((folder / 'download-receipt.json').read_text())
            repository, revision, size = MODELS[lang]
            if receipt['repository'] != repository or receipt['revision'] != revision:
                raise ValueError('Wrong pinned specialist')
            for row in receipt['files']:
                if digest(folder / row['name']) != row['sha256']:
                    raise ValueError('Specialist asset changed')
            vocab = json.loads((folder / 'vocab.json').read_text())
            if len(vocab) != size or sorted(vocab.values()) != list(range(size)) or vocab['<pad>'] != 0:
                raise ValueError('Unexpected trained specialist output IDs')
            vocabs[lang] = vocab
            extractor = Wav2Vec2FeatureExtractor.from_pretrained(folder, local_files_only=True)
            inputs = extractor(audio, sampling_rate=16000, padding=False, return_tensors='pt')
            if inputs.input_values.shape != (1, count):
                raise ValueError('Frontend changed waveform length')
            model, loading = load_strict(folder)
            guard.check()
            forward_started = time.monotonic()
            with torch.inference_mode():
                logits = model(**inputs).logits[0]
                log_probs = logits.log_softmax(-1).cpu().numpy()
            guard.check()
            # Keep original full logits before masking any reserved IDs.
            retained = output.with_name(output.stem + '-' + lang + '.npz')
            with retained.open('xb') as file:
                np.savez_compressed(file, log_probs=log_probs)
            head = {'model': repository, 'revision': revision, 'vocab': vocab,
                    'asset_receipt_sha256': digest(folder / 'download-receipt.json'),
                    'retained_logits_sha256': digest(retained), 'loading': loading,
                    'shape': list(log_probs.shape), 'forward_s': time.monotonic() - forward_started,
                    'load_and_forward_s': time.monotonic() - before,
                    'greedy': collapse(log_probs.argmax(-1).tolist(), vocab)}
            save(output.with_name(output.stem + '-' + lang + '.json'), head)
            result['heads'][lang] = head
            print(lang, head['greedy']['raw_text'], flush=True)
            adjusted = log_probs.astype(np.float64)
            adjusted[:, [vocab['<s>'], vocab['</s>'], vocab['<unk>']]] = -np.inf
            adjusted -= np.logaddexp.reduce(adjusted, axis=1, keepdims=True)
            arrays[lang] = adjusted
            del model, logits, inputs
            gc.collect()
        if arrays['eng'].shape[0] != arrays['rus'].shape[0]:
            raise ValueError('Different trained frame grids; do not interpolate')
        for name, score in (('no-context', 0.), ('context', 2.5)):
            before = time.monotonic()
            value = search(arrays, vocabs, score, guard.check, hint_case='upper')
            value['decode_s'] = time.monotonic() - before
            save(output.with_name(output.stem + '-' + name + '.json'), value)
            result['variants'][name] = value
            print(name, value['hypotheses'][0]['raw_text'], flush=True)
        result['status'] = 'success'
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        result.update(elapsed_s=time.monotonic() - started,
                      peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                      guard=guard.receipt())
        save(output, result)


def replay(args):
    import numpy as np
    parent, output = Path(args.receipt), Path(args.output)
    if output.exists():
        raise FileExistsError('Consumed whole-word decoder cell')
    original = json.loads(parent.read_text())
    arrays, vocabs = {}, {}
    for lang in LANGS:
        path = parent.with_name(parent.stem + '-' + lang + '.npz')
        if digest(path) != original['heads'][lang]['retained_logits_sha256']:
            raise ValueError('Retained specialist logits changed')
        vocab = original['heads'][lang]['vocab']
        vocabs[lang] = vocab
        with np.load(path) as file:
            adjusted = file['log_probs'].astype(np.float64)
        adjusted[:, [vocab['<s>'], vocab['</s>'], vocab['<unk>']]] = -np.inf
        adjusted -= np.logaddexp.reduce(adjusted, axis=1, keepdims=True)
        arrays[lang] = adjusted
    guard = Guard(180, 1536)
    before = time.monotonic()
    value = search(arrays, vocabs, 2.5, guard.check, hint_case='upper', whole_word_context=True)
    value.update(decode_s=time.monotonic() - before, parent_sha256=digest(parent),
                 source_commit=subprocess.check_output(['git', '-C', str(Path(__file__).parent), 'rev-parse', 'HEAD'], text=True).strip(),
                 encoder_rerun=False, audio_sha256=original['audio_sha256'],
                 peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                 guard=guard.receipt())
    save(output, value)
    print(value['hypotheses'][0]['raw_text'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='mode', required=True)
    c = sub.add_parser('cell')
    for key in ('model', 'wav', 'audio-sha256', 'output'):
        c.add_argument('--' + key, required=True)
    p = sub.add_parser('pilot')
    p.add_argument('manifest')
    r = sub.add_parser('replay')
    r.add_argument('--receipt', required=True)
    r.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.mode == 'cell': cell(args)
    elif args.mode == 'replay': replay(args)
    else: supervise(args, cell_script=__file__)
