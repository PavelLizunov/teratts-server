"""Opt-in full FastAPI import and multipart boundary; all model/hardware work stubbed.

Run BONSAI_ASGI_TEST=1 in the existing Deck gateway environment. No sockets,
production service, inference, private audio or configuration is used.
"""
from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import wave

TOOLS = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get("BONSAI_ASGI_TEST") == "1", "explicit ASGI environment opt-in required")
class TestFullGatewayASGI(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Imports are inside the opt-in; normal local checks need no web dependencies.
        import httpx
        import numpy  # Keep extension modules outside patch.dict(sys.modules) restoration.
        from PIL import Image
        self.httpx = httpx
        sys.path.insert(0, str(TOOLS / "stt-dictionary"))
        sys.path.insert(0, str(TOOLS / "bonsai-normalizer"))
        import stt_dictionary
        import bonsai_normalizer
        self.normalizer_module = bonsai_normalizer
        startup_env = getattr(self, 'editor_startup_env', {})
        installed_dir = getattr(self, 'installed_gateway_dir', None)
        if installed_dir:
            spec = importlib.util.spec_from_file_location('installed_stt_dictionary', Path(installed_dir) / 'stt_dictionary.py')
            stt_dictionary = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(stt_dictionary)
        self.env = patch.dict(os.environ, {
            "STT_BACKEND": "parakeet", "STT_CORRECTOR": "loqira",
            "STT_DICTIONARY_CONFIG": str(TOOLS / "stt-dictionary/deploy/stt-dictionary.json"),
            "BONSAI_GATEWAY_TEST_SOURCE": os.environ.get("BONSAI_GATEWAY_TEST_SOURCE", str(TOOLS / "ruen-support-pilot/gateway-server.py")),
            **startup_env,
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

        def module(name, **attributes):
            result = ModuleType(name)
            result.__dict__.update(attributes)
            return result

        class Formatter:
            def __init__(self, *_):
                pass
            def __call__(self, text):
                return text, {"segments": [{"candidate_text": text}], "status": "applied"}

        class Loqira:
            def __init__(self, *_):
                pass
            def __call__(self, text):
                return text, {"status": "applied", "loqira_ms": 0.0, "sage_ms": 0.0}
            def ready(self):
                return True

        package = module("gateway")
        package.__path__ = [str(installed_dir)] if installed_dir else []
        stubs = {
            "gateway": package,
            "gateway.stt_dictionary": stt_dictionary,
            "gateway.speech_formatting": module("gateway.speech_formatting", Formatter=Formatter),
            "gateway.loqira_corrector": module("gateway.loqira_corrector", LoqiraCorrector=Loqira,
                IDENTITY={"model": "stub-loqira"}, POLICY="stub"),
            "onnxruntime": module("onnxruntime", SessionOptions=lambda: SimpleNamespace(),
                InferenceSession=lambda *a, **k: object()),
            "transformers": module("transformers", AutoTokenizer=SimpleNamespace(from_pretrained=lambda *a, **k: object())),
            "transcribe_cpp": module("transcribe_cpp"),
            "rapidocr": module("rapidocr", RapidOCR=lambda **k: lambda *a: None,
                OCRVersion=SimpleNamespace(PPOCRV5="stub"), LangRec=SimpleNamespace(CYRILLIC="stub"),
                ModelType=SimpleNamespace(MOBILE="stub")),
        }
        self.modules = patch.dict(sys.modules, stubs)
        self.modules.start()
        self.addCleanup(self.modules.stop)
        # Fail if an import/initializer tries any model or HTTP path unexpectedly.
        self.network = patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("network forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)
        path = Path(os.environ.get("BONSAI_GATEWAY_TEST_SOURCE", str(TOOLS / "ruen-support-pilot/gateway-server.py")))
        spec = importlib.util.spec_from_file_location("gateway_asgi_snapshot", path)
        self.gateway = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.gateway)
        self.gateway.run_parakeet = lambda _: "Ну, смотри, открой гитхап"
        self.gateway.voice_corpus = MagicMock()
        self.gateway.voice_corpus.save.return_value = "synthetic-sample"
        self.normalizer = MagicMock(model="stub-bonsai", revision="stub", enabled=True)
        self.normalizer.normalize.side_effect = lambda text: (text, {"status": "applied"})
        if not startup_env:
            self.gateway.bonsai_normalizer = self.normalizer
            os.environ["BONSAI_NORMALIZER_CONFIG"] = "in-memory-test-only"
        audio = io.BytesIO()
        with wave.open(audio, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\0\0" * 16)
        self.audio = audio.getvalue()
        self.transport = httpx.ASGITransport(app=self.gateway.app)

    async def post(self, client, query="", response_format="json"):
        return await client.post("/v1/audio/transcriptions" + query,
            files={"file": ("synthetic.wav", self.audio, "audio/wav")},
            data={"response_format": response_format})

    def test_health_reports_actual_editor_identity_without_editor_call(self):
        with patch.object(self.gateway.local_http, 'open') as opened:
            opened.return_value.__enter__.return_value.read.return_value = b'{"ready": true}'
            health = self.gateway.health()
        self.assertEqual(health['text_editor'], {'status': 'configured', 'model': 'stub-bonsai', 'revision': 'stub'})
        self.normalizer.normalize.assert_not_called()

    async def test_real_multipart_precedence_provenance_and_formats(self):
        cases = (("?mode=default&cleanup=true", "bypassed"),
                 ("?mode=raw", "bypassed"),
                 ("?mode=smart&format=false", "bypassed"),
                 ("?mode=raw&format=false&smart=true&cleanup=true", "applied"),
                 ("?mode=smart&dictionary=false&cleanup=false", "applied"))
        async with self.httpx.AsyncClient(transport=self.transport, base_url="http://asgi.test") as client:
            for query, status in cases:
                for fmt in ("text", "json"):
                    with self.subTest(query=query, response_format=fmt):
                        self.normalizer.normalize.reset_mock()
                        response = await self.post(client, query, fmt)
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.headers["x-bonsai-status"], status)
                        record = self.gateway.voice_corpus.save.call_args.args[1]
                        text = response.text if fmt == "text" else response.json()["text"]
                        self.assertEqual(text, record["accepted_stt_text"])
                        self.assertEqual(text, record["final_text"])
                        if status == "bypassed":
                            self.normalizer.normalize.assert_not_called()
                            self.assertEqual(response.headers["x-bonsai-latency-ms"], "0.0")
                        else:
                            self.normalizer.normalize.assert_called_once_with(record["accepted_stt_text"])
                        if "dictionary=false" in query:
                            self.assertEqual(text, record["raw_text"])
                        if "cleanup=true" in query:
                            self.assertEqual(text, "открой GitHub")

    async def test_bolt_real_multipart_smart_only_and_explicit_optouts(self):
        from bolt_normalizer import BoltNormalizer, BOLT_MODEL, BOLT_REVISION
        normalizer = BoltNormalizer()
        self.gateway.bonsai_normalizer = normalizer
        os.environ['BOLT_NORMALIZER_CONFIG'] = 'in-memory-test-only'
        candidate = 'Открой GitHub.\n\nПроверь настройки сервера.'
        body = {'model': BOLT_MODEL, 'revision': BOLT_REVISION,
                'choices': [{'finish_reason': 'stop', 'message': {
                    'role': 'assistant', 'content': candidate}}]}
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps(body).encode()
        cases = (('', False), ('?mode=default', False), ('?smart=false', False),
                 ('?mode=smart', True), ('?smart=true', True),
                 ('?mode=default&smart=true', True), ('?mode=smart&smart=false', True),
                 ('?mode=raw', False), ('?mode=raw&smart=true', False),
                 ('?format=false', False), ('?smart=true&format=false', False),
                 ('?mode=smart&format=false&smart=true', False))
        async with self.httpx.AsyncClient(transport=self.transport, base_url='http://asgi.test') as client:
            for query, edited in cases:
                for fmt in ('json', 'text'):
                    with self.subTest(query=query, fmt=fmt), patch.object(
                            normalizer._opener, 'open', return_value=mock_response) as opened:
                        response = await self.post(client, query, fmt)
                        self.assertEqual(response.status_code, 200)
                        record = self.gateway.voice_corpus.save.call_args.args[1]
                        text = response.text if fmt == 'text' else response.json()['text']
                        self.assertEqual(text, candidate if edited else record['accepted_stt_text'])
                        self.assertEqual(record['final_text'], text)
                        self.assertEqual(response.headers['x-text-editor-status'],
                                         'applied' if edited else 'bypassed')
                        self.assertEqual(opened.call_count, int(edited))

    async def test_real_serialization_and_exact_fallback(self):
        source = "Проверь сервер."
        self.gateway.run_parakeet = lambda _: source
        normalizer_module = self.normalizer_module
        body = {"model": normalizer_module.DEFAULT_MODEL, "revision": normalizer_module.DEFAULT_REVISION,
            "choices": [{"finish_reason": "stop", "message": {"content": source + "\ud800"}}]}
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps(body).encode()
        real_normalizer = normalizer_module.BonsaiNormalizer()
        self.gateway.bonsai_normalizer = real_normalizer
        async with self.httpx.AsyncClient(transport=self.transport, base_url="http://asgi.test") as client:
            for fmt in ("text", "json"):
                with patch.object(real_normalizer._opener, "open", return_value=mock_response):
                    response = await self.post(client, "?mode=smart", fmt)
                self.assertEqual(response.status_code, 200)
                text = response.text if fmt == "text" else response.json()["text"]
                self.assertEqual(text, source)
                self.assertEqual(response.headers["x-bonsai-status"], "fallback")
                record = self.gateway.voice_corpus.save.call_args.args[1]
                self.assertEqual(record["bonsai"]["reason"], "invalid_content_encoding")
                self.assertEqual(record["accepted_stt_text"], record["final_text"])
            self.gateway.bonsai_normalizer = self.normalizer
            self.normalizer.normalize.side_effect = TimeoutError("not logged")
            response = await self.post(client, "?mode=smart")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["text"], source)
            self.assertEqual(response.headers["x-bonsai-status"], "fallback")

    async def test_raw_request_completes_while_smart_waits(self):
        started = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        observed = []
        def block(text):
            loop.call_soon_threadsafe(started.set)
            observed.append(release.wait(2))
            return text, {"status": "applied"}
        self.normalizer.normalize.side_effect = block
        async with self.httpx.AsyncClient(transport=self.transport, base_url="http://asgi.test") as client:
            smart = asyncio.create_task(self.post(client, "?mode=smart"))
            try:
                await asyncio.wait_for(started.wait(), timeout=1)
                response = await asyncio.wait_for(self.post(client, "?mode=raw"), timeout=1)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["x-bonsai-status"], "bypassed")
                self.assertFalse(smart.done())
            finally:
                release.set()
                smart_response = await smart
            self.assertEqual(smart_response.status_code, 200)
            self.assertEqual(observed, [True])


if __name__ == "__main__":
    unittest.main()
