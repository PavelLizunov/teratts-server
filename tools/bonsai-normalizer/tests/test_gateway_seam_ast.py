"""AST and static analysis test for gateway-server.py integration seam.

Verifies seam placement, condition gating, header injection, corpus record additions,
and readiness reporting without requiring unavailable hardware dependencies (Vulkan/ASR).
"""

from __future__ import annotations

import ast
import asyncio
import copy
import io
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "stt-dictionary"))
from stt_dictionary import apply_dictionary, clean_opening

GATEWAY_SERVER_PATH = (
    Path(__file__).resolve().parents[2]
    / "ruen-support-pilot"
    / "gateway-server.py"
)


class TestGatewaySeamAST(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GATEWAY_SERVER_PATH.is_file():
            raise AssertionError(f"Not found: {GATEWAY_SERVER_PATH}")
        cls.source = GATEWAY_SERVER_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source, filename=str(GATEWAY_SERVER_PATH))

    def test_syntax_valid(self):
        """gateway-server.py must parse cleanly without syntax errors."""
        self.assertIsInstance(self.tree, ast.Module)

    def test_bonsai_normalizer_import_and_initialization(self):
        """bonsai_normalizer must be initialized with loqira corrector and config checks."""
        self.assertIn("bonsai_normalizer = None", self.source)
        self.assertIn('os.environ.get("BONSAI_NORMALIZER_CONFIG")', self.source)
        self.assertIn('STT_CORRECTOR == "loqira"', self.source)
        self.assertIn("from gateway.bonsai_normalizer import get_bonsai_normalizer", self.source)

    def test_readyz_reports_bonsai_status(self):
        """health() must report bonsai status without network calls."""
        health_fn = None
        for node in self.tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "health":
                health_fn = node
                break

        self.assertIsNotNone(health_fn, "health() function not found")
        # Find return statement
        ret_node = None
        for node in ast.walk(health_fn):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                ret_node = node.value
                break

        self.assertIsNotNone(ret_node, "health() return dict not found")
        dict_keys = [
            k.value for k in ret_node.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        ]
        self.assertIn("bonsai", dict_keys)

    def test_seam_placement_and_gating_in_transcribe_audio(self):
        """transcribe_audio must place bonsai seam after clean_opening with strict gating."""
        transcribe_fn = None
        for node in self.tree.body:
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "transcribe_audio":
                transcribe_fn = node
                break

        self.assertIsNotNone(transcribe_fn, "transcribe_audio function not found")

        # Verify key code elements exist in the function
        func_source = ast.get_source_segment(self.source, transcribe_fn)
        self.assertIsNotNone(func_source)

        # 1. clean_opening must precede accepted_stt_text capture
        idx_clean = func_source.find("clean_opening(final_text, cleanup)")
        idx_accepted = func_source.find("accepted_stt_text = final_text")
        self.assertNotEqual(idx_clean, -1, "clean_opening call missing")
        self.assertNotEqual(idx_accepted, -1, "accepted_stt_text assignment missing")
        self.assertLess(idx_clean, idx_accepted, "accepted_stt_text must be captured after clean_opening")

        # 2. Strict gating condition
        self.assertIn('effective_mode == "smart"', func_source)
        self.assertIn('STT_CORRECTOR == "loqira"', func_source)
        self.assertIn('os.environ.get("BONSAI_NORMALIZER_CONFIG")', func_source)

        # 3. Call to normalizer with accepted_stt_text
        self.assertIn("bonsai_normalizer.normalize(accepted_stt_text)", func_source)

        # 4. Fallback preserves accepted_stt_text
        self.assertIn("final_text = accepted_stt_text", func_source)
        self.assertIn("final_text = rewritten_text", func_source)

    def test_headers_and_server_timing(self):
        """Headers must include X-Bonsai-Status, X-Bonsai-Latency-Ms, X-Bonsai-Model and Server-Timing."""
        self.assertIn('"X-Bonsai-Status": bonsai_meta.get("status", "bypassed")', self.source)
        self.assertIn('"X-Bonsai-Latency-Ms": f"{bonsai_latency_ms:.1f}"', self.source)
        self.assertIn('headers["X-Bonsai-Model"] = str(bonsai_meta["model"])', self.source)
        self.assertIn("bonsai;dur={bonsai_latency_ms:.1f}", self.source)

    def test_corpus_preserves_distinct_accepted_stt_text_and_bonsai_meta(self):
        """Corpus payload must record accepted_stt_text, bonsai metadata, and final_text."""
        self.assertIn('"accepted_stt_text": accepted_stt_text', self.source)
        self.assertIn('"final_text": final_text', self.source)
        self.assertIn('"bonsai": bonsai_meta', self.source)
        self.assertIn('"bonsai": bonsai_latency_ms', self.source)


class TestExecutedGatewaySeam(unittest.TestCase):
    """Execute the real function AST, never hardware initialization or HTTP."""

    def _execute(self, mode="smart", smart=False, formatting=True, configured=True,
                 corrector="loqira", has_loqira=True, dictionary=True, cleanup=True,
                 result=None, error=None, response_format="json"):
        tree = ast.parse(GATEWAY_SERVER_PATH.read_text())
        function = copy.deepcopy(next(n for n in tree.body
                                      if isinstance(n, ast.AsyncFunctionDef) and n.name == "transcribe_audio"))
        function.decorator_list = []
        function.args.defaults = []  # Pass all arguments explicitly; no FastAPI initialization.
        events = []
        dictionary_path = Path(__file__).resolve().parents[2] / "stt-dictionary/deploy/stt-dictionary.json"

        def dictionary_pass(text, path, enabled):
            events.append(("dictionary", text))
            return apply_dictionary(text, path, enabled)

        def loqira_pass(text):
            events.append(("loqira", text))
            return text, {"status": "applied", "loqira_ms": 1.0, "sage_ms": 0.0}

        def cleanup_pass(text, enabled):
            events.append(("cleanup", text))
            return clean_opening(text, enabled)

        normalizer = Mock(model="bonsai", revision="revision", enabled=True)

        def normalize(text):
            events.append(("bonsai", text))
            if error:
                raise error
            return result if result is not None else ("Нейтральный текст.", {"status": "applied"})

        normalizer.normalize.side_effect = normalize
        corpus = Mock()
        corpus.save.return_value = "sample-id"
        source = "Ну, смотри, открой гитхап"
        namespace = {
            "__name__": "gateway_contract_test", "Optional": __import__("typing").Optional,
            "Request": object, "UploadFile": object, "io": io, "wave": wave,
            "time": time, "os": os, "np": SimpleNamespace(int16=object(), float32=object(),
                frombuffer=lambda *a, **kw: SimpleNamespace(astype=lambda _: 0.0)),
            "STT_BACKEND": "parakeet", "STT_CORRECTOR": corrector,
            "STT_IDENTITY": {"model": "parakeet", "model_revision": "pinned"},
            "CORRECTOR_IDENTITY": {"model": "loqira"}, "CORRECTOR_POLICY": "loqira-policy",
            "run_parakeet": Mock(return_value=source), "apply_dictionary": dictionary_pass,
            "loqira_corrector": Mock(side_effect=loqira_pass) if has_loqira else None,
            "run_smart_structuring": Mock(return_value=(source, True)),
            "clean_opening": cleanup_pass, "bonsai_normalizer": normalizer,
            "voice_corpus": corpus, "stt_context": lambda _: {},
            "JSONResponse": lambda **kw: SimpleNamespace(**kw),
            "Response": lambda **kw: SimpleNamespace(**kw), "HTTPException": RuntimeError,
            "print": Mock(),
        }
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                     str(GATEWAY_SERVER_PATH), "exec"), namespace)
        audio = io.BytesIO()
        with wave.open(audio, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\0\0" * 16)
        env = {"STT_DICTIONARY_CONFIG": str(dictionary_path)}
        if configured:
            env["BONSAI_NORMALIZER_CONFIG"] = "configured.json"
        with patch.dict(os.environ, env, clear=True):
            response = asyncio.run(namespace["transcribe_audio"](
                request=None, file=SimpleNamespace(read=AsyncMock(return_value=audio.getvalue())),
                language=None, response_format=response_format, mode=mode, smart=smart,
                format=formatting, dictionary=dictionary, cleanup=cleanup))
        return response, corpus.save.call_args.args[1], normalizer, events, namespace

    def test_default_and_raw_bypass_actual_normalizer(self):
        for options in ({"mode": "default"}, {"mode": "raw"},
                        {"mode": "smart", "formatting": False}):
            with self.subTest(options=options):
                response, record, normalizer, events, _ = self._execute(**options)
                normalizer.normalize.assert_not_called()
                self.assertEqual(response.headers["X-Bonsai-Status"], "bypassed")
                self.assertEqual(response.headers["X-Bonsai-Latency-Ms"], "0.0")
                self.assertEqual(record["timings_ms"]["bonsai"], 0.0)
                self.assertEqual(record["final_text"], record["accepted_stt_text"])
                if response.headers["X-Mode"] == "raw":
                    self.assertNotIn("loqira", [e[0] for e in events])

    def test_smart_stage_order_headers_and_corpus(self):
        response, record, normalizer, events, namespace = self._execute()
        self.assertEqual([e[0] for e in events], ["dictionary", "loqira", "dictionary", "cleanup", "bonsai"])
        self.assertEqual(events[1][1], "Ну, смотри, открой GitHub")
        accepted = "открой GitHub"
        normalizer.normalize.assert_called_once_with(accepted)
        namespace["run_smart_structuring"].assert_not_called()
        self.assertEqual(record["raw_text"], "Ну, смотри, открой гитхап")
        self.assertEqual(record["accepted_stt_text"], accepted)
        self.assertEqual(record["final_text"], "Нейтральный текст.")
        self.assertEqual(response.content, {"text": "Нейтральный текст."})
        self.assertEqual(response.headers["X-Bonsai-Status"], "applied")
        self.assertIn("bonsai;dur=", response.headers["Server-Timing"])
        self.assertEqual(response.headers["X-Corpus-Sample-ID"], "sample-id")

    def test_smart_flag_keeps_existing_precedence_over_format_false(self):
        response, _, normalizer, _, _ = self._execute(mode="raw", smart=True, formatting=False)
        self.assertEqual(response.headers["X-Mode"], "smart")
        normalizer.normalize.assert_called_once()

    def test_dictionary_cleanup_optouts_preserved(self):
        _, record, normalizer, _, _ = self._execute(dictionary=False, cleanup=False)
        normalizer.normalize.assert_called_once_with(record["raw_text"])
        self.assertEqual(record["accepted_stt_text"], record["raw_text"])

    def test_unconfigured_or_non_loqira_bypasses(self):
        for options in ({"configured": False}, {"corrector": "sage", "has_loqira": False},
                        {"has_loqira": False}):
            with self.subTest(options=options):
                response, _, normalizer, _, _ = self._execute(**options)
                normalizer.normalize.assert_not_called()
                self.assertEqual(response.headers["X-Bonsai-Latency-Ms"], "0.0")

    def test_fallback_and_exceptions_preserve_accepted_text(self):
        for options in (
            {"result": ("wrong candidate", {"status": "fallback", "reason": "timeout"})},
            {"error": TimeoutError("private transcript and token")},
            {"result": ("bad", None)}, {"result": (None, {"status": "applied"})},
            {"result": ("", {"status": "applied"})},
        ):
            with self.subTest(options=options):
                response, record, _, _, _ = self._execute(**options, response_format="text")
                self.assertEqual(response.content, record["accepted_stt_text"])
                self.assertEqual(record["final_text"], record["accepted_stt_text"])
                self.assertEqual(response.headers["X-Bonsai-Status"], "fallback")
                self.assertNotIn("private transcript", str(record["bonsai"]))

    def test_health_does_not_probe_bonsai(self):
        tree = ast.parse(GATEWAY_SERVER_PATH.read_text())
        function = copy.deepcopy(next(n for n in tree.body
                                      if isinstance(n, ast.FunctionDef) and n.name == "health"))
        function.decorator_list = []
        normalizer = Mock(enabled=True)
        namespace = {"STT_BACKEND": "gigaam", "STT_IDENTITY": {}, "SAGE_READY": True,
                     "CORRECTOR_IDENTITY": {}, "CORRECTOR_POLICY": "policy",
                     "loqira_corrector": None, "bonsai_normalizer": normalizer}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(GATEWAY_SERVER_PATH), "exec"), namespace)
        self.assertEqual(namespace["health"]()["bonsai"], "configured")
        normalizer.normalize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
