import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import wave
import hashlib

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("selector", ROOT / "select_voice_teacher_pilot.py")
selector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selector)


def fixture(root, i, kind="stt", synthetic=False, silence=False, duration=3):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
        audio.writeframes((b"\0\0" if silence else bytes([i % 255 + 1, 0])) * (duration * 16000))
    wav = buf.getvalue()
    metadata = {"kind": kind, "sample_id": f"sample-{i}", "audio_origin": "submitted_stt_request",
                "raw_text": "текст", "audio_sha256": hashlib.sha256(wav).hexdigest(),
                "client_context": {"headers": {"x-request-id": "synthetic-test" if synthetic else "real"}}}
    path = root / f"{i:04d}.tar"
    with tarfile.open(path, "w") as archive:
        for name, data in [("sample.json", json.dumps(metadata).encode()), ("original.wav", wav)]:
            info = tarfile.TarInfo(name); info.size = len(data); archive.addfile(info, io.BytesIO(data))
    return path


class Tests(unittest.TestCase):
    def test_excludes_synthetic_tts_silence_and_long(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root, 1)
            fixture(root, 2, kind="tts_http")
            fixture(root, 3, synthetic=True)
            fixture(root, 4, silence=True)
            fixture(root, 5, duration=31)
            result = selector.select(root)
            self.assertEqual(result["selected_samples"], 1)
            self.assertFalse(result["external_upload_started"])
            self.assertNotIn("raw_text", result["samples"][0])

    def test_cap_and_reproducibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(50): fixture(root, i, duration=20)
            first = selector.select(root)
            self.assertEqual(first, selector.select(root))
            self.assertLessEqual(first["selected_samples"], 20)
            self.assertLessEqual(first["total_duration_s"], 300)
            self.assertEqual(first["eligible_unique_samples"], 50)

    def test_dedup_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = fixture(root, 1)
            (root / "0002.tar").write_bytes(path.read_bytes())
            (root / "0003.tar").symlink_to(path)
            self.assertEqual(selector.select(root)["selected_samples"], 1)

    def test_empty_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bad.tar").write_bytes(b"bad")
            self.assertEqual(selector.select(root)["selected_samples"], 0)

if __name__ == "__main__": unittest.main(verbosity=2)
