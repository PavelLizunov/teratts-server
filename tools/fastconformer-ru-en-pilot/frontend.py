"""NumPy implementation of this checkpoint's NeMo 1.21 eval frontend.

Source: NeMo c0022aec9c8fedd59458935f0378a775b28d0444,
parts/preprocessing/features.py FilterbankFeatures. This follows the math,
not a claimed bit-exact Torch implementation. No appended waveform silence.
"""
import wave


def nemo_features(path, config):
    import numpy as np
    expected = {'sample_rate': 16000, 'window_size': .025,
                'window_stride': .01, 'window': 'hann', 'features': 80,
                'n_fft': 512, 'frame_splicing': 1, 'pad_to': 0,
                'normalize': 'per_feature'}
    if any(config.get(k) != v for k, v in expected.items()):
        raise ValueError('Unsupported frontend checkpoint configuration')
    with wave.open(str(path), 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (1, 2, 16000, 'NONE'):
            raise ValueError('Whole original mono16 PCM WAV required')
        count = wav.getnframes()
        x = np.frombuffer(wav.readframes(count), dtype='<i2').astype(np.float32) / 32768
    if len(x) != count or count <= 512:
        raise ValueError('Truncated or short original WAV')
    # NeMo eval: no dithering; global preemphasis before centered STFT.
    x = np.concatenate((x[:1], x[1:] - np.float32(.97) * x[:-1]))
    window = np.pad(np.hanning(400).astype(np.float32), (56, 56))
    frames = np.lib.stride_tricks.sliding_window_view(np.pad(x, (256, 256), mode='reflect'), 512)[::160]
    spectrum = np.fft.rfft(frames * window, axis=-1)
    power = (np.abs(spectrum) ** 2).astype(np.float32)
    # librosa Slaney mel, including area normalization, no external scipy/librosa.
    logstep = np.log(6.4) / 27.0
    maxmel = 15.0 + np.log(8000.0 / 1000.0) / logstep
    mels = np.linspace(0.0, maxmel, 82)
    hz = mels * (200.0 / 3.0)
    logarithmic = mels >= 15.0
    hz[logarithmic] = 1000.0 * np.exp(logstep * (mels[logarithmic] - 15.0))
    fftfreq = np.fft.rfftfreq(512, 1.0 / 16000)
    ramps = hz[:, None] - fftfreq[None, :]
    diffs = np.diff(hz)
    weights = np.maximum(0.0, np.minimum(-ramps[:-2] / diffs[:-1, None], ramps[2:] / diffs[1:, None])).astype(np.float32)
    weights *= (2.0 / (hz[2:] - hz[:-2]))[:, None]
    features = np.log(power @ weights.T + np.float32(2.0 ** -24))
    features = (features - features.mean(axis=0, keepdims=True)) / (features.std(axis=0, ddof=1, keepdims=True) + np.float32(1e-5))
    if len(features) != count // 160 + 1 or not np.isfinite(features).all():
        raise ValueError('Invalid NeMo-aligned feature output')
    return np.ascontiguousarray(features, dtype=np.float32), count / 16000
