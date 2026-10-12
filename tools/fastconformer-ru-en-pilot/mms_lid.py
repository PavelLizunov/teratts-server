"""Whole-audio LID contributions, NOT a frame-supervised language diarizer.

The published sequence classifier has linear projector, mean pooling, linear
classifier. Its frame contributions average to its official utterance logits.
Attention remains global; aggregation identity does not prove localization.
"""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import wave

from mms_pair import digest, save, supervise, repair_weight_names

REV = '53da6e311f3ce48f324fe335924216187e3109a4'


def cell(args):
    output, root = Path(args.output), Path(args.model)
    if output.exists() or output.with_suffix('.npz').exists():
        raise FileExistsError('Consumed/unknown LID cell')
    started = time.monotonic()
    result = {'status': 'failed', 'parameters': vars(args), 'revision': REV,
              'source_commit': subprocess.check_output(['git', '-C', str(Path(__file__).parent), 'rev-parse', 'HEAD'], text=True).strip(),
              'host': os.uname().nodename, 'trial_started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'segmentation': False, 'audio_padding': False, 'transcript_input': False,
              'frame_supervised': False, 'calibrated_temporal_language_detection': False}
    try:
        import numpy as np
        import torch
        from transformers import Wav2Vec2FeatureExtractor, Wav2Vec2ForSequenceClassification
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        torch.manual_seed(0)
        result['runtime_versions'] = {k: importlib.metadata.version(k) for k in ('torch', 'transformers', 'accelerate', 'numpy', 'safetensors')}
        assets = json.loads((root / 'download-receipt.json').read_text())
        if assets['revision'] != REV:
            raise ValueError('Wrong independent LID revision')
        for item in assets['files']:
            if digest(root / item['name']) != item['sha256']:
                raise ValueError('LID asset changed: ' + item['name'])
        if digest(args.wav) != args.audio_sha256:
            raise ValueError('Original audio changed')
        result['asset_receipt_sha256'] = digest(root / 'download-receipt.json')
        with wave.open(args.wav, 'rb') as file:
            if (file.getnchannels(), file.getsampwidth(), file.getframerate(), file.getcomptype()) != (1, 2, 16000, 'NONE'):
                raise ValueError('Whole original mono16 PCM required')
            count = file.getnframes()
            audio = np.frombuffer(file.readframes(count), dtype='<i2').astype(np.float32) / 32768.
        extractor = Wav2Vec2FeatureExtractor.from_pretrained(root, local_files_only=True)
        inputs = extractor(audio, sampling_rate=16000, padding=False, return_tensors='pt')
        if inputs['input_values'].shape != (1, count) or not bool(inputs['attention_mask'].all()):
            raise ValueError('Waveform shape or attention mask changed')
        model, loading = Wav2Vec2ForSequenceClassification.from_pretrained(
            root, local_files_only=True, use_safetensors=True, low_cpu_mem_usage=True,
            torch_dtype=torch.float32, attn_implementation='sdpa', output_loading_info=True)
        result['loading_info'] = loading
        result['weight_name_migration'] = repair_weight_names(model, loading, root)
        model.eval()
        if model.config.id2label[2] != 'eng' or model.config.id2label[26] != 'rus':
            raise ValueError('Unexpected trained class map')
        if model.config.use_weighted_layer_sum:
            raise ValueError('Unsupported LID weighted-layer architecture')
        result['runtime_model_source_sha256'] = digest(sys.modules[model.__class__.__module__].__file__)
        result['load_and_frontend_s'] = time.monotonic() - started
        projected = []
        hook = model.projector.register_forward_hook(lambda module, inp, out: projected.append(out.detach()))
        forward_started = time.monotonic()
        with torch.inference_mode():
            official = model(**inputs).logits
            hook.remove()
            if len(projected) != 1:
                raise ValueError('Expected exactly one official encoder/projector call')
            frames = model.classifier(projected[0])[0]
            mean_frames = frames.mean(dim=0)
            error = float((mean_frames - official[0]).abs().max())
            if not torch.allclose(mean_frames, official[0], atol=1e-4, rtol=1e-5):
                raise ValueError('Frame contributions do not reproduce official logits')
            pair = frames[:, [2, 26]].softmax(-1)
            global_probs = official[0].softmax(-1)
        result['one_forward_s'] = time.monotonic() - forward_started
        # Valid convolutional features: exact stride and receptive-field centers.
        jump, receptive = 1, 1
        for kernel, stride in zip(model.config.conv_kernel, model.config.conv_stride):
            receptive += (kernel - 1) * jump
            jump *= stride
        expected_frames = (count - receptive) // jump + 1
        if len(frames) != expected_frames:
            raise ValueError('Unexpected LID frame axis')
        centers = (np.arange(len(frames)) * jump + (receptive - 1) / 2.) / 16000.
        p = pair.cpu().numpy()
        with output.with_suffix('.npz').open('xb') as file:
            np.savez_compressed(file, frame_logits=frames.cpu().numpy(), global_logits=official[0].cpu().numpy(),
                                pair_probabilities=p, frame_centers_s=centers)
        runs = []
        begin, active = 0, int(p[0].argmax())
        for t in range(1, len(p) + 1):
            next_active = int(p[t].argmax()) if t < len(p) else None
            if next_active != active:
                runs.append({'language': ('eng', 'rus')[active], 'first_frame': begin, 'last_frame': t - 1,
                             'first_center_s': float(centers[begin]), 'last_center_s': float(centers[t-1]),
                             'mean_pair_conditional_probability': float(p[begin:t, active].mean())})
                begin, active = t, next_active
        top = torch.topk(global_probs, 5)
        result.update(status='success', audio_sha256=args.audio_sha256, audio_duration_s=count / 16000.,
                      input_samples=count, feature_frames=len(frames), convolution_stride_samples=jump,
                      convolution_receptive_samples=receptive, aggregate_max_abs_error=error,
                      retained_frame_sha256=digest(output.with_suffix('.npz')),
                      global_top5=[{'language': model.config.id2label[int(i)], 'probability': float(v)} for i, v in zip(top.indices, top.values)],
                      pair_class_ids={'eng': 2, 'rus': 26},
                      english_pair_probability={'min': float(p[:, 0].min()), 'median': float(np.median(p[:, 0])),
                                                'max': float(p[:, 0].max()), 'mean': float(p[:, 0].mean())},
                      english_dominant_frames=int((p[:, 0] > p[:, 1]).sum()),
                      pair_argmax_runs=runs,
                      limitation='Whole-utterance supervised, global-attention frame contributions; not verified switch timestamps')
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        result.update(elapsed_s=time.monotonic() - started,
                      peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
        save(output, result)
        print(json.dumps(result, ensure_ascii=False), flush=True)


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
    else: supervise(args, cell_script=__file__)
