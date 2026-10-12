"""One whole-recording isolated CPU trial with durable raw numerical output."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import resource
import subprocess
import sys
import time
import wave

from decoder import ContextBias, decode


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def memory_snapshot():
    result = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        if key in ('MemAvailable', 'SwapTotal', 'SwapFree'):
            result[key] = int(value.split()[0]) * 1024
    result['swap_used'] = result['SwapTotal'] - result['SwapFree']
    return result


def sensors():
    # Actual readable Deck hwmon values, not assumed sensor IDs.
    temperatures, fans = {}, {}
    for hw in Path('/sys/class/hwmon').glob('hwmon*'):
        for pattern, target in (('temp*_input', temperatures), ('fan*_input', fans)):
            for path in hw.glob(pattern):
                try:
                    target[str(path)] = int(path.read_text())
                except (OSError, ValueError):
                    pass
    return {'temperatures_millic': temperatures, 'fan_rpm': fans}


class Guard:
    def __init__(self, seconds, max_rss_mib):
        self.started = time.monotonic()
        self.seconds = seconds
        self.max_rss = max_rss_mib * 1048576
        self.initial_memory = memory_snapshot()
        self.initial_sensors = sensors()
        self.peak_temperatures = dict(self.initial_sensors['temperatures_millic'])
        self.min_available = self.initial_memory['MemAvailable']
        self.max_swap_growth = 0
        self.last_sample = 0.0
        self.last_sensors = self.initial_sensors
        self.stop_reason = None
        self.check()

    def check(self):
        now = time.monotonic()
        reason = None
        if now - self.started > self.seconds:
            reason = 'recording_timeout'
        peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        if peak_rss > self.max_rss:
            reason = 'process_rss_limit'
        if now - self.last_sample >= 0.5:
            memory, sensor = memory_snapshot(), sensors()
            self.last_sample, self.last_sensors = now, sensor
            self.min_available = min(self.min_available, memory['MemAvailable'])
            growth = memory['swap_used'] - self.initial_memory['swap_used']
            self.max_swap_growth = max(self.max_swap_growth, growth)
            if memory['MemAvailable'] < 2048 * 1048576:
                reason = 'available_memory_floor'
            if growth > 256 * 1048576:
                reason = 'swap_growth_limit'
            for path, value in sensor['temperatures_millic'].items():
                self.peak_temperatures[path] = max(value, self.peak_temperatures.get(path, value))
            if any(t >= 85000 for t in sensor['temperatures_millic'].values()):
                reason = 'thermal_limit'
        if reason:
            self.stop_reason = reason
            raise RuntimeError(reason)

    def receipt(self):
        return {'initial_memory_bytes': self.initial_memory,
                'minimum_available_bytes': self.min_available,
                'maximum_swap_growth_bytes': self.max_swap_growth,
                'initial_sensors': self.initial_sensors,
                'last_sensors': self.last_sensors,
                'peak_temperatures_millic': self.peak_temperatures,
                'stop_reason': self.stop_reason}


class OnnxModel:
    def __init__(self, root, artifacts, threads):
        import numpy as np
        import onnxruntime as ort
        self.np = np
        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = threads
        self.sessions = {}
        for kind in ('encoder', 'decoder', 'joiner'):
            self.sessions[kind] = ort.InferenceSession(
                str(root / (kind + '.int8.onnx')), sess_options=options,
                providers=['CPUExecutionProvider'])
        self.meta = self.sessions['encoder'].get_modelmeta().custom_metadata_map
        self.layers = int(self.meta['pred_rnn_layers'])
        self.hidden = int(self.meta['pred_hidden'])
        self.normalize = self.meta['normalize_type']
        if self.normalize != artifacts['preprocessor']['normalize']:
            raise ValueError('Export normalization differs from original checkpoint')
        if int(self.meta['vocab_size']) not in (artifacts['blank_id'], artifacts['blank_id'] + 1):
            raise ValueError('Export metadata vocabulary differs from original')
        pred = artifacts['decoder']
        if self.layers != pred['pred_rnn_layers'] or self.hidden != pred['pred_hidden']:
            raise ValueError('Prediction state shape differs from original')
        self.signature = {kind: {'inputs': [str(x) for x in s.get_inputs()],
                                'outputs': [str(x) for x in s.get_outputs()]}
                          for kind, s in self.sessions.items()}

    def initial_states(self):
        return tuple(self.np.zeros((self.layers, 1, self.hidden), dtype=self.np.float32)
                     for _ in range(2))

    def predict(self, token, states):
        s, np = self.sessions['decoder'], self.np
        values = [np.array([[token]], dtype=np.int32), np.array([1], dtype=np.int32), *states]
        outputs = s.run(None, {x.name: value for x, value in zip(s.get_inputs(), values)})
        if len(outputs) != 4:
            raise ValueError('Unsupported prediction network signature')
        return outputs[0], (outputs[2], outputs[3])

    def join(self, encoded_frame, prediction):
        s = self.sessions['joiner']
        return s.run(None, {s.get_inputs()[0].name: encoded_frame,
                            s.get_inputs()[1].name: prediction})[0]

    def encode(self, features):
        np, s = self.np, self.sessions['encoder']
        tensor = np.ascontiguousarray(features.T[None], dtype=np.float32)
        outputs = s.run(None, {s.get_inputs()[0].name: tensor,
                              s.get_inputs()[1].name: np.array([len(features)], dtype=np.int64)})
        return outputs[0], int(outputs[1].reshape(-1)[0])


def features_from_wav(path, preprocessor):
    import kaldi_native_fbank as knf
    import numpy as np
    with wave.open(str(path), 'rb') as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, 16000, 'NONE'):
            raise ValueError('Pilot requires original 16kHz mono PCM16 WAV; no resample/downmix')
        frames = audio.getnframes()
        samples = np.frombuffer(audio.readframes(frames), dtype='<i2').astype(np.float32) / 32768
    if len(samples) != frames or frames < 400:
        raise ValueError('Truncated or too short original WAV')
    options = knf.FbankOptions()
    options.frame_opts.dither = 0
    options.frame_opts.remove_dc_offset = False
    options.frame_opts.window_type = preprocessor['window']
    options.frame_opts.frame_length_ms = preprocessor['window_size'] * 1000
    options.frame_opts.frame_shift_ms = preprocessor['window_stride'] * 1000
    options.mel_opts.low_freq = 0
    options.mel_opts.num_bins = preprocessor['features']
    options.mel_opts.is_librosa = True
    fbank = knf.OnlineFbank(options)
    fbank.accept_waveform(16000, samples)
    features = np.stack([fbank.get_frame(i) for i in range(fbank.num_frames_ready)]).astype(np.float32)
    if preprocessor['normalize'] != 'per_feature':
        raise ValueError('Unsupported checkpoint feature normalization')
    features = (features - features.mean(axis=0, keepdims=True)) / (
        features.std(axis=0, ddof=1, keepdims=True) + 1e-5)
    return features.astype(np.float32), frames / 16000


def context_paths(root, artifacts, hints):
    import sentencepiece as spm
    tokenizers = {lang: spm.SentencePieceProcessor(model_file=str(root / name))
                  for lang, name in artifacts['tokenizer_models'].items()}
    paths, receipts = [], []
    for hint in hints:
        ids = []
        for segment in hint['segments']:
            lang, text = segment['lang'], segment['text']
            if lang not in tokenizers:
                raise ValueError('Hint requests a forbidden language')
            tokenizer = tokenizers[lang]
            local = tokenizer.encode(text, out_type=int)
            if not local or tokenizer.unk_id() in local:
                raise ValueError('Hint contains out-of-vocabulary characters: ' + text)
            offset = artifacts['languages'][lang]['offset']
            ids.extend(i + offset for i in local)
        paths.append(ids)
        receipts.append({'segments': hint['segments'], 'token_ids': ids})
    return paths, receipts


def run(args):
    root, output = Path(args.artifacts), Path(args.output)
    if output.exists():
        raise FileExistsError('Refuse to repeat/overwrite a trial receipt')
    output.parent.mkdir(parents=True, exist_ok=True)
    guard = Guard(args.seconds, args.max_rss_mib)
    receipt = {'status': 'failed', 'audio_sha256': digest(args.wav),
               'artifacts_manifest_sha256': digest(root / 'artifacts.json'),
               'source_commit': subprocess.check_output(
                   ['git', '-C', str(Path(__file__).parent), 'rev-parse', 'HEAD'], text=True).strip(),
               'parameters': vars(args), 'host': 'steamdeck CPU',
               'segmentation': False, 'audio_padding': False,
               'bias_enabled': not args.no_bias, 'postprocessing': 'none',
               'trial_started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    started = time.monotonic()
    try:
        if receipt['audio_sha256'] != args.audio_sha256:
            raise ValueError('Original audio hash mismatch')
        artifacts = json.loads((root / 'artifacts.json').read_text())
        for name, expected in artifacts['files_sha256'].items():
            if digest(root / name) != expected:
                raise ValueError('Prepared model/tokenizer changed: ' + name)
        hints = [] if args.no_bias else json.loads(Path(args.hints).read_text())
        paths, path_receipts = context_paths(root, artifacts, hints)
        receipt['context_paths'] = path_receipts
        receipt['allowed_token_ids'] = artifacts['allowed_token_ids']
        receipt['blank_id'] = artifacts['blank_id']
        model = OnnxModel(root, artifacts, args.threads)
        guard.check()
        features, duration = features_from_wav(Path(args.wav), artifacts['preprocessor'])
        receipt.update(audio_duration_s=duration, feature_frames=len(features),
                       model_metadata=model.meta, model_signature=model.signature)
        encoded, length = model.encode(features)
        guard.check()
        receipt['encoded_frames'] = length
        decoding_started = time.monotonic()
        result = decode(model, encoded, length, artifacts['allowed_token_ids'],
                        artifacts['blank_id'], ContextBias(paths, args.bias_score),
                        beam=args.beam, max_symbols=args.max_symbols, check=guard.check)
        tokens = {}
        for line in (root / 'tokens.txt').read_text().splitlines():
            piece, idx = line.rsplit(' ', 1)
            tokens[int(idx)] = piece
        result['tokens'] = [tokens[i] for i in result['token_ids']]
        result['raw_text'] = ''.join(result['tokens']).replace('▁', ' ').strip()
        result['postprocessed_text'] = result['raw_text']
        result['timestamps_s'] = [i * .08 for i in result['frame_indices']]
        receipt.update(result, status='success', decoding_s=time.monotonic() - decoding_started)
    except Exception as error:
        receipt['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        receipt['elapsed_s'] = time.monotonic() - started
        receipt['peak_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        receipt['guard'] = guard.receipt()
        receipt['runtime_versions'] = {name: importlib.metadata.version(name) for name in (
            'numpy', 'onnxruntime', 'kaldi-native-fbank', 'sentencepiece', 'PyYAML')}
        # Exclusive result creation keeps failed and unknown attempts visible.
        with output.open('x') as file:
            json.dump(receipt, file, ensure_ascii=False, indent=2)
        output.chmod(0o600)
        print(json.dumps(receipt, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifacts', required=True)
    parser.add_argument('--wav', required=True)
    parser.add_argument('--audio-sha256', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--hints')
    parser.add_argument('--no-bias', action='store_true')
    parser.add_argument('--bias-score', type=float, default=1.5)
    parser.add_argument('--beam', type=int, default=4)
    parser.add_argument('--max-symbols', type=int, default=10)
    parser.add_argument('--threads', type=int, default=1)
    parser.add_argument('--seconds', type=int, default=180)
    parser.add_argument('--max-rss-mib', type=int, default=1536)
    args = parser.parse_args()
    if not args.no_bias and not args.hints:
        parser.error('--hints is required unless --no-bias')
    run(args)
