import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import wave

from prepare import control_bytes, prepare
from run import atomic_json, validate_record
from collect import collect


class PilotTests(unittest.TestCase):
    def test_negative_controls_are_fixed_pcm(self):
        for noise in (False, True):
            data = control_bytes(noise)
            self.assertEqual(data, control_bytes(noise))
            with wave.open(io.BytesIO(data)) as w:
                self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()),
                                 (1, 2, 16000, 16000))
                pcm = w.readframes(16000)
            self.assertEqual(set(pcm) == {0}, not noise)

    def test_changed_audio_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'audio.wav'
            data = control_bytes()
            p.write_bytes(data)
            row = dict(id='test', path=str(p), sha256=hashlib.sha256(data).hexdigest())
            self.assertEqual(validate_record(row), p)
            p.write_bytes(data + b'change')
            with self.assertRaises(ValueError):
                validate_record(row)

    def test_invalid_private_ids_rejected_before_ssh(self):
        with self.assertRaises(ValueError):
            prepare('/unused', ['../private', 'wrong'])

    def test_failed_receipts_are_not_completed_comparisons(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'manifest.json').write_text('{"records": []}')
            (root / 'parakeet-results.json').write_text('{"exit_code": 1}')
            with self.assertRaises(ValueError):
                collect(root)
            self.assertFalse((root / 'comparison-private.json').exists())

    def test_atomic_private_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'result.json'
            atomic_json(p, {'status': 'failed', 'text': 'русский'})
            self.assertEqual(json.loads(p.read_text())['text'], 'русский')
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            self.assertFalse(p.with_suffix('.part').exists())


if __name__ == '__main__':
    unittest.main()
