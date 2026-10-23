"""AST and static analysis test for gateway-server.py integration seam.

Verifies seam placement, condition gating, header injection, corpus record additions,
and readiness reporting without requiring unavailable hardware dependencies (Vulkan/ASR).
"""

from __future__ import annotations

import ast
import asyncio
import copy
import io
import json
import os
from pathlib import Path
import sys
import threading
import tempfile
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
        self.assertIn("await asyncio.to_thread(bonsai_normalizer.normalize, accepted_stt_text)", func_source)

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
                 result=None, error=None, response_format="json", real_normalizer=None,
                 asr_text="Ну, смотри, открой гитхап", loqira_text=None,
                 dictionary_path=None):
        tree = ast.parse(GATEWAY_SERVER_PATH.read_text())
        function = copy.deepcopy(next(n for n in tree.body
                                      if isinstance(n, ast.AsyncFunctionDef) and n.name == "transcribe_audio"))
        function.decorator_list = []
        function.args.defaults = []  # Pass all arguments explicitly; no FastAPI initialization.
        events = []
        if dictionary_path is None:
            dictionary_path = Path(__file__).resolve().parents[2] / "stt-dictionary/deploy/stt-dictionary.json"

        def dictionary_pass(text, path, enabled):
            events.append(("dictionary", text))
            return apply_dictionary(text, path, enabled)

        def loqira_pass(text):
            events.append(("loqira", text))
            return text if loqira_text is None else loqira_text, {
                "status": "applied", "loqira_ms": 1.0, "sage_ms": 0.0}

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
        if real_normalizer is not None:
            normalizer = real_normalizer
        corpus = Mock()
        corpus.save.return_value = "sample-id"
        source = asr_text
        namespace = {
            "__name__": "gateway_contract_test", "Optional": __import__("typing").Optional,
            "Request": object, "UploadFile": object, "io": io, "wave": wave,
            "time": time, "os": os, "asyncio": asyncio, "np": SimpleNamespace(int16=object(), float32=object(),
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

    def test_changed_loqira_provenance_and_exact_post_cleanup_fallback(self):
        raw = "Ну, смотри, найди гитхап"
        corrected = "Ну, смотри, открой омарчи.\r\n\tНе меняй порт 4713.  "
        post_dictionary = "Ну, смотри, открой Omarchy.\r\n\tНе меняй порт 4713.  "
        accepted = "открой Omarchy.\r\n\tНе меняй порт 4713.  "
        outcomes = [
            {"result": ("rejected candidate", {"status": status})}
            for status in ("fallback", "unchanged", "bypassed", "unexpected_status")
        ] + [
            {"error": TimeoutError("private error payload")},
            {"error": RuntimeError("private error payload")},
            {"result": ("invalid metadata", None)},
            {"result": (None, {"status": "applied"})},
            {"result": (" \r\n\t", {"status": "applied"})},
        ]
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "dictionary.json"
            config.write_text(json.dumps({"github": True, "omarchy": True}))
            original = config.read_bytes()
            for fmt in ("text", "json"):
                for index, outcome in enumerate(outcomes):
                    with self.subTest(response_format=fmt, outcome=index):
                        response, record, normalizer, events, namespace = self._execute(
                            asr_text=raw, loqira_text=corrected, dictionary_path=config,
                            response_format=fmt, **outcome)
                        self.assertEqual(events, [
                            ("dictionary", raw),
                            ("loqira", "Ну, смотри, найди GitHub"),
                            ("dictionary", corrected),
                            ("cleanup", post_dictionary),
                            ("bonsai", accepted),
                        ])
                        self.assertEqual(record["raw_text"], raw)
                        self.assertEqual(record["pre_dictionary_text"], corrected)
                        self.assertEqual(record["pre_cleanup_text"], post_dictionary)
                        self.assertEqual(record["accepted_stt_text"], accepted)
                        normalizer.normalize.assert_called_once_with(accepted)
                        actual = response.content if fmt == "text" else response.content["text"]
                        self.assertEqual(actual.encode("utf-8"), accepted.encode("utf-8"))
                        self.assertEqual(record["final_text"], accepted)
                        for wrong_stage in (raw, "Ну, смотри, найди GitHub", corrected, post_dictionary):
                            self.assertNotEqual(actual, wrong_stage)
                        self.assertNotIn("private error payload", str(record["bonsai"]))
                        namespace["run_smart_structuring"].assert_not_called()
            self.assertEqual(config.read_bytes(), original)

    def test_routing_matrix_keeps_accepted_stage_and_optin_isolation(self):
        raw = "Ну, смотри, найди гитхап"
        corrected = "Ну, смотри, открой омарчи.\r\n\tСохрани 4713.  "
        accepted_raw = "найди GitHub"
        accepted_corrected = "открой Omarchy.\r\n\tСохрани 4713.  "
        candidate = "Заменён только экспериментальный результат."
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "dictionary.json"
            config.write_text(json.dumps({"github": True, "omarchy": True}))
            for mode in ("raw", "default", "smart"):
                for smart in (False, True):
                    for formatting in (False, True):
                        with self.subTest(mode=mode, smart=smart, formatting=formatting):
                            effective = "smart" if smart else "raw" if not formatting else mode
                            response, record, normalizer, events, namespace = self._execute(
                                asr_text=raw, loqira_text=corrected, dictionary_path=config,
                                mode=mode, smart=smart, formatting=formatting,
                                result=(candidate, {"status": "applied"}))
                            accepted = accepted_raw if effective == "raw" else accepted_corrected
                            self.assertEqual(response.headers["X-Mode"], effective)
                            self.assertEqual(record["accepted_stt_text"], accepted)
                            if effective == "smart":
                                normalizer.normalize.assert_called_once_with(accepted)
                                self.assertEqual(record["final_text"], candidate)
                                self.assertEqual(response.headers["X-Bonsai-Status"], "applied")
                            else:
                                normalizer.normalize.assert_not_called()
                                self.assertEqual(record["final_text"], accepted)
                                self.assertEqual(response.headers["X-Bonsai-Status"], "bypassed")
                                self.assertEqual(response.headers["X-Bonsai-Latency-Ms"], "0.0")
                            self.assertEqual(response.content, {"text": record["final_text"]})
                            namespace["run_smart_structuring"].assert_not_called()
                            self.assertEqual("loqira" in [event[0] for event in events], effective != "raw")

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

    @patch("urllib.request.OpenerDirector.open")
    def test_real_normalizer_rejection_reaches_gateway_response(self, mock_open):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from bonsai_normalizer import BonsaiNormalizer, DEFAULT_MODEL, DEFAULT_REVISION

        source = "Не удаляй базу, перезапусти сервер."
        body = {
            "model": DEFAULT_MODEL, "revision": DEFAULT_REVISION,
            "choices": [{"finish_reason": "stop", "message": {
                "content": "Удаляй базу, не перезапусти сервер."}}],
        }
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps(body).encode("utf-8")
        mock_open.return_value = mock_response
        response, record, _, _, _ = self._execute(
            real_normalizer=BonsaiNormalizer(), asr_text=source)
        self.assertEqual(response.content, {"text": source})
        self.assertEqual(record["accepted_stt_text"], source)
        self.assertEqual(record["final_text"], source)
        self.assertEqual(record["bonsai"]["reason"], "validation_word_order_changed")
        self.assertEqual(response.headers["X-Bonsai-Status"], "fallback")
        mock_open.assert_called_once()

    @patch("urllib.request.OpenerDirector.open")
    def test_invalid_unicode_candidate_falls_back_in_both_formats(self, mock_open):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from bonsai_normalizer import BonsaiNormalizer, DEFAULT_MODEL, DEFAULT_REVISION
        source = "Проверь сервер."
        body = {"model": DEFAULT_MODEL, "revision": DEFAULT_REVISION,
            "choices": [{"finish_reason": "stop", "message": {"content": source + "\ud800"}}]}
        response_mock = MagicMock()
        response_mock.__enter__.return_value = response_mock
        response_mock.read.return_value = json.dumps(body).encode("utf-8")
        mock_open.return_value = response_mock
        for response_format in ("text", "json"):
            with self.subTest(response_format=response_format):
                response, record, _, _, _ = self._execute(real_normalizer=BonsaiNormalizer(),
                    asr_text=source, response_format=response_format)
                self.assertEqual(record["final_text"], source)
                self.assertEqual(record["bonsai"]["reason"], "invalid_content_encoding")
                content = response.content
                encoded = (content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)).encode("utf-8")
                self.assertTrue(encoded)
                self.assertEqual(response.headers["X-Bonsai-Status"], "fallback")

    @patch("urllib.request.OpenerDirector.open")
    def test_literal_editor_exact_fallback_and_edit_reach_real_gateway_function(self, opened):
        from bonsai_literal_editor import BonsaiLiteralEditor
        from bonsai_normalizer import DEFAULT_MODEL, DEFAULT_REVISION
        source = 'Этот дурацкий таймер ждёт 7 секунд.'
        for selection, expected, status in (
            ('{"delete":[0]}', 'Этот таймер ждёт 7 секунд.', 'applied'),
            ('{"delete":[999]}', source, 'fallback'),
            ('{"delete":[]}', source, 'unchanged'),
        ):
            body = {'model': DEFAULT_MODEL, 'revision': DEFAULT_REVISION,
                    'choices': [{'finish_reason': 'stop', 'message': {'content': selection}}]}
            mock_response = MagicMock()
            mock_response.__enter__.return_value = mock_response
            mock_response.read.return_value = json.dumps(body).encode()
            opened.return_value = mock_response
            response, record, _, _, _ = self._execute(
                real_normalizer=BonsaiLiteralEditor(), asr_text=source)
            self.assertEqual(record['accepted_stt_text'], source)
            self.assertEqual(record['final_text'], expected)
            self.assertEqual(response.content, {'text': expected})
            self.assertEqual(response.headers['X-Bonsai-Status'], status)

    @patch("urllib.request.OpenerDirector.open")
    def test_paragraph_selection_preserves_accepted_source_in_real_gateway(self, opened):
        from bonsai_paragraph_structurer import BonsaiParagraphStructurer
        from bonsai_normalizer import DEFAULT_MODEL, DEFAULT_REVISION
        source = 'Сохрани отчёт. Проверь копию. Позвони Анне.'
        for selection, expected, status in (
            ('{"break_after":[1]}', source.replace('Позвони', '\n\nПозвони'), 'applied'),
            ('{"break_after":[999]}', source, 'fallback'),
            ('{"break_after":[]}', source, 'unchanged'),
        ):
            body = {'model': DEFAULT_MODEL, 'revision': DEFAULT_REVISION,
                    'choices': [{'finish_reason': 'stop', 'message': {'content': selection}}]}
            mock_response = MagicMock()
            mock_response.__enter__.return_value = mock_response
            mock_response.read.return_value = json.dumps(body).encode()
            opened.return_value = mock_response
            response, record, _, _, _ = self._execute(
                real_normalizer=BonsaiParagraphStructurer(), asr_text=source)
            self.assertEqual(record['accepted_stt_text'], source)
            self.assertEqual(record['final_text'], expected)
            self.assertEqual(response.content, {'text': expected})
            self.assertEqual(response.headers['X-Bonsai-Status'], status)

    def test_blocked_normalizer_yields_event_loop(self):
        # A deterministic callback, not a fragile wall-time threshold, releases the mock.
        class LoopProbe:
            model, revision, enabled = "bonsai", "revision", True
            def __init__(self):
                self.callback_ran_during_wait = False
            def normalize(self, text):
                released = threading.Event()
                self.loop.call_soon_threadsafe(released.set)
                self.callback_ran_during_wait = released.wait(0.5)
                return text, {"status": "applied"}
        probe = LoopProbe()
        original_run = asyncio.run
        def run_with_loop(coroutine):
            async def wrapped():
                probe.loop = asyncio.get_running_loop()
                return await coroutine
            return original_run(wrapped())
        with patch.object(asyncio, "run", side_effect=run_with_loop):
            response, record, _, _, _ = self._execute(real_normalizer=probe)
        self.assertTrue(probe.callback_ran_during_wait)
        self.assertEqual(record["final_text"], record["accepted_stt_text"])
        self.assertEqual(response.headers["X-Bonsai-Status"], "applied")

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
