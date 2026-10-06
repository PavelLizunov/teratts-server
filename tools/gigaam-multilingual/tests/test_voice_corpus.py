"""Local archive and isolated gateway contract tests; no live models required."""
import ast
import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "stt-dictionary"))
spec = importlib.util.spec_from_file_location("voice_corpus", ROOT / "voice_corpus.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Corpus = module.Corpus


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "corpus"
        self.corpus = Corpus(self.root, max_bytes=30_720, min_free_bytes=0)

    def tearDown(self):
        self.temp.cleanup()

    def test_pair_roundtrip_permissions_and_hash(self):
        sample = self.corpus.save(b"test audio", {"raw_text": "текст", "final_text": "Текст."})
        with tarfile.open(self.root / f"{sample}.tar") as archive:
            self.assertEqual(archive.getnames(), ["original.wav", "sample.json"])
            self.assertEqual(archive.extractfile("original.wav").read(), b"test audio")
            data = json.load(archive.extractfile("sample.json"))
            self.assertIsNone(data["human_reference_text"])
            self.assertEqual(data["raw_text"], "текст")
            self.assertEqual(len(data["audio_sha256"]), 64)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.root / f"{sample}.tar").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.root / ".lock").stat().st_mode), 0o600)

    def test_oldest_complete_sample_evicted(self):
        samples = [self.corpus.save(b"a", {"number": i}) for i in range(4)]
        self.assertFalse((self.root / f"{samples[0]}.tar").exists())
        self.assertEqual(self.corpus.status()["samples"], 3)
        self.assertLessEqual(self.corpus.status()["bytes"], 30_720)

    def test_oversized_keeps_existing(self):
        self.corpus.save(b"small", {})
        self.assertIsNone(self.corpus.save(b"x" * 40_000, {}))
        self.assertEqual(self.corpus.status()["samples"], 1)
        self.assertIsNone(self.corpus.save(b"x" * (10 * 1024 * 1024 + 1), {}))

    def test_concurrent_writers(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(lambda i: self.corpus.save(b"a", {"i": i}), range(32)))
        self.assertEqual(len(set(ids)), 32)
        self.assertEqual(self.corpus.status()["samples"], 3)
        for p in self.root.glob("*.tar"):
            with tarfile.open(p) as archive:
                self.assertEqual(len(archive.getnames()), 2)

    def test_orphan_partial_cleaned_only_under_lock(self):
        orphan = self.root / ("." + "0" * 20 + "-" + "a" * 32 + ".tar.tmp")
        orphan.write_bytes(b"partial")
        self.corpus.save(b"a", {})
        self.assertFalse(orphan.exists())

    def test_write_failure_removes_partial(self):
        with patch.object(module.os, "fsync", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.corpus.save(b"a", {})
        self.assertEqual(list(self.root.glob("*.tmp")), [])
        self.assertEqual(self.corpus.status()["samples"], 0)

    def test_symlink_not_followed_or_deleted(self):
        outside = Path(self.temp.name) / "important"
        outside.write_text("keep")
        link = self.root / ("0" * 20 + "-" + "a" * 32 + ".tar")
        link.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.corpus.save(b"a", {})
        self.assertEqual(outside.read_text(), "keep")
        self.assertTrue(link.is_symlink())

    def test_hardlink_not_deleted(self):
        outside = Path(self.temp.name) / "important"
        outside.write_text("keep")
        os.link(outside, self.root / "unknown")
        with self.assertRaises(ValueError):
            self.corpus.save(b"a", {})
        self.assertEqual(outside.read_text(), "keep")

    def test_unknown_files_counted_not_deleted(self):
        unknown = self.root / "not-owned.txt"
        unknown.write_bytes(b"u" * 30_000)
        self.assertIsNone(self.corpus.save(b"a", {}))
        self.assertTrue(unknown.exists())
        self.assertEqual(self.corpus.status()["bytes"], 30_000)

    def test_free_headroom(self):
        with patch.object(module.shutil, "disk_usage", return_value=type("Disk", (), {"free": 100})()):
            self.assertIsNone(self.corpus.save(b"a", {}))
        self.assertEqual(self.corpus.status()["samples"], 0)

    def test_quota_never_exceeds_user_authorization(self):
        with self.assertRaises(ValueError):
            Corpus(self.root, max_bytes=50_000_000_001)

    def test_root_symlink_rejected(self):
        link = Path(self.temp.name) / "link"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            Corpus(link)

    def test_lock_symlink_rejected(self):
        outside = Path(self.temp.name) / "important"
        outside.write_text("keep")
        (self.root / ".lock").symlink_to(outside)
        with self.assertRaises(OSError):
            self.corpus.save(b"a", {})
        self.assertEqual(outside.read_text(), "keep")


class GatewayContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Compile the exact deployment handler, not a separately copied implementation.
        tree = ast.parse((ROOT / "deploy/gateway-server.py").read_text())
        handler = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "transcribe_audio")
        handler.decorator_list = []
        handler.args.defaults = [ast.Constant(None) for _ in handler.args.defaults]
        handler.returns = None
        for arg in handler.args.args:
            arg.annotation = None
        cls.code = compile(ast.fix_missing_locations(ast.Module(body=[handler], type_ignores=[])), "actual-gateway-handler", "exec")

    def run_handler(self, corpus, fmt="json", mode="raw", raw="тест", corrector=None, dictionary=True, cleanup=False, backend='parakeet'):
        import numpy as np
        class Upload:
            async def read(self):
                buf = io.BytesIO()
                with wave.open(buf, "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(16000)
                    output.writeframes(b"\0\0" * 1600)
                return buf.getvalue()
        class Response:
            def __init__(self, content, headers, **kwargs):
                self.content, self.headers = content, headers
        class HTTPException(Exception):
            def __init__(self, **kwargs):
                self.kwargs = kwargs
        env = {"io": io, "time": time, "wave": wave, "np": np,
               "STT_BACKEND": backend, "run_parakeet": lambda audio: raw,
               "run_gigaam_multilingual": lambda audio:raw,
               "STT_METADATA": {'model':'ai-sage/GigaAM-Multilingual' if backend=='gigaam_multilingual' else 'nvidia/parakeet-tdt-0.6b-v3',
                                'model_revision':'3905cd51c3ed4e88c8edf33f3302969ba480a327' if backend=='gigaam_multilingual' else '541d1f99c6b0c3cd0b11a95167540bb8edefd82b',
                                'quantization':'none' if backend=='gigaam_multilingual' else 'Q8_0'},
               "run_smart_structuring": lambda text: ("• Тест", True),
               "voice_corpus": corpus, "Response": Response, "JSONResponse": Response,
               "HTTPException": HTTPException, "stt_context": lambda request: {},
               "clean_opening": __import__('stt_dictionary').clean_opening,
               "os": os, "apply_dictionary": corrector or (lambda text,path,requested: (text,{"status":"config_disabled","changes":[]}))}
        exec(self.code, env)
        return asyncio.run(env["transcribe_audio"](None, Upload(), "ru", fmt, mode, False, True, dictionary, cleanup))

    def test_json_and_text_contract_and_metadata(self):
        class Spy:
            def save(self, audio, metadata):
                self.audio, self.metadata = audio, metadata
                return "sample-id"
        spy = Spy()
        response = self.run_handler(spy)
        self.assertEqual(response.content, {"text": "тест"})
        self.assertEqual(response.headers["X-Corpus-Sample-ID"], "sample-id")
        total_headers = [key for key in response.headers if key.lower() == "x-total-latency-ms"]
        self.assertEqual(total_headers, ["X-Total-Latency-Ms"])
        self.assertGreaterEqual(float(response.headers["X-Total-Latency-Ms"]),
                                float(response.headers["X-STT-Latency-Ms"]))
        self.assertEqual(spy.metadata["raw_text"], "тест")
        self.assertEqual(spy.metadata["audio_duration_s"], 0.1)
        self.assertNotIn("headers", spy.metadata)
        self.assertEqual(self.run_handler(spy, "text").content, "тест")
        smart = self.run_handler(spy, mode="smart")
        self.assertEqual(smart.content["text"], "• Тест")
        self.assertEqual(spy.metadata["raw_text"], "тест")
        self.assertEqual(spy.metadata["final_text"], "• Тест")

    def test_github_rule_preserves_original_metadata_and_optout(self):
        spec = importlib.util.spec_from_file_location("rule", ROOT.parent / "stt-dictionary/stt_dictionary.py")
        rule = importlib.util.module_from_spec(spec); spec.loader.exec_module(rule)
        class Spy:
            def save(self,audio,metadata):self.metadata=metadata;return "sample-id"
        spy=Spy()
        with tempfile.TemporaryDirectory() as tmp:
            config=Path(tmp)/"rule.json";config.write_text('{"github":true}')
            corrector=lambda text,path,requested:rule.apply_dictionary(text,config,requested)
            result=self.run_handler(spy,raw="На Гитхап.",corrector=corrector)
            self.assertEqual(result.content,{"text":"На GitHub."})
            self.assertEqual(spy.metadata["raw_text"],"На Гитхап.")
            self.assertEqual(spy.metadata["pre_dictionary_text"],"На Гитхап.")
            self.assertEqual(spy.metadata["dictionary"]["changes"][0]["before"],"Гитхап")
            self.assertEqual(result.headers["X-Dictionary-Changes"],"1")
            off=self.run_handler(spy,fmt="text",raw="На Гитхап.",corrector=corrector,dictionary=False)
            self.assertEqual(off.content,"На Гитхап.")
            self.assertEqual(off.headers["X-Dictionary-Status"],"request_disabled")

    def test_chatgpt_pro_and_plugin_actual_handler(self):
        spec=importlib.util.spec_from_file_location('rule',ROOT.parent/'stt-dictionary/stt_dictionary.py')
        rule=importlib.util.module_from_spec(spec);spec.loader.exec_module(rule)
        class Spy:
            def save(self,audio,metadata):self.metadata=metadata;return 'sample-id'
        spy=Spy()
        with tempfile.TemporaryDirectory() as tmp:
            config=Path(tmp)/'r.json';config.write_text('{"chatgpt":true,"plugin":true}')
            corrector=lambda text,path,requested:rule.apply_dictionary(text,config,requested)
            raw='Открой чат GPT Pro и плагины.'
            result=self.run_handler(spy,raw=raw,corrector=corrector)
            self.assertEqual(result.content['text'],'Открой ChatGPT Pro и plugin.')
            self.assertEqual(spy.metadata['raw_text'],raw)
            self.assertEqual(len(spy.metadata['dictionary']['changes']),2)
            self.assertEqual(self.run_handler(spy,raw=raw,corrector=corrector,dictionary=False).content['text'],raw)

    def test_restored_parakeet_model_metadata(self):
        class Spy:
            def save(self,audio,metadata):self.metadata=metadata;return 'sample'
        spy=Spy();result=self.run_handler(spy,raw='Тест Parakeet',backend='parakeet')
        self.assertEqual(result.content['text'],'Тест Parakeet')
        self.assertEqual(result.headers['X-STT-Backend'],'parakeet')
        self.assertEqual(spy.metadata['model'],'nvidia/parakeet-tdt-0.6b-v3')
        self.assertEqual(spy.metadata['model_revision'],'541d1f99c6b0c3cd0b11a95167540bb8edefd82b')
        self.assertNotIn('engine_version',spy.metadata)

    def test_new_multilingual_is_not_old_gigaam_or_sage(self):
        class Spy:
            def save(self,audio,metadata):self.metadata=metadata;return 'sample'
        spy=Spy();r=self.run_handler(spy,backend='gigaam_multilingual',mode='default',raw='новый текст')
        self.assertEqual(r.content['text'],'новый текст')
        self.assertEqual(spy.metadata['model'],'ai-sage/GigaAM-Multilingual')
        self.assertEqual(spy.metadata['quantization'],'none')
        self.assertEqual(r.headers['X-SAGE-Latency-Ms'],'0.0')
        self.assertEqual(self.run_handler(spy,backend='gigaam_multilingual',mode='smart').content['text'],'• Тест')

    def test_cleanup_default_and_provenance(self):
        class Spy:
            def save(self,audio,metadata):self.metadata=metadata;return 'sample-id'
        spy=Spy();raw='Смотри, плагины работают.'
        self.assertEqual(self.run_handler(spy,raw=raw).content['text'],raw)
        result=self.run_handler(spy,raw=raw,cleanup=True)
        self.assertEqual(result.content['text'],'плагины работают.')
        self.assertEqual(spy.metadata['raw_text'],raw)
        self.assertEqual(spy.metadata['pre_cleanup_text'],raw)
        self.assertEqual(result.headers['X-Cleanup-Changes'],'1')

    def test_collection_failure_does_not_break_stt(self):
        class Broken:
            def save(self, *args):
                raise OSError("test")
        response = self.run_handler(Broken())
        self.assertEqual(response.content, {"text": "тест"})
        self.assertNotIn("X-Corpus-Sample-ID", response.headers)

    def test_disabled_collection_unchanged(self):
        response = self.run_handler(None)
        self.assertEqual(response.content, {"text": "тест"})
        self.assertNotIn("X-Corpus-Sample-ID", response.headers)


if __name__ == "__main__":
    unittest.main(verbosity=2)
