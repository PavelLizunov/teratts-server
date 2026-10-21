"""Comprehensive unit tests for Mac Bonsai 9B neutral transcript normalizer.

Validates bypass behaviors, timeout capping, mock HTTP responses, protocol failures,
rejection constraints (growth, numbers, Latin identifiers, negations), and secrets safety.
"""

from __future__ import annotations

import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bonsai_normalizer import (
    DEFAULT_MODEL,
    DEFAULT_REVISION,
    SYSTEM_PROMPT,
    BonsaiNormalizer,
    BonsaiNormalizerConfig,
    count_negation_tokens,
    extract_latin_identifiers,
    extract_numeric_tokens,
    get_bonsai_normalizer,
)


def _make_mock_response(
    content: str,
    finish_reason: str = "stop",
    model: str = DEFAULT_MODEL,
    revision: str = DEFAULT_REVISION,
    status_code: int = 200,
) -> MagicMock:
    data = {
        "id": "bonsai9-test",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "bonsai": {
            "revision": revision,
            "cold": False,
        },
    }
    body = json.dumps(data).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.status = status_code
    mock_resp.__enter__.return_value = mock_resp
    return mock_resp


class TestBonsaiNormalizerConfig(unittest.TestCase):
    def test_default_timeout_and_hard_cap(self):
        cfg = BonsaiNormalizerConfig()
        self.assertEqual(cfg.effective_timeout, 12.0)

        cfg_high = BonsaiNormalizerConfig(timeout_seconds=25.0)
        self.assertEqual(cfg_high.effective_timeout, 20.0)

        cfg_custom = BonsaiNormalizerConfig(timeout_seconds=15.0)
        self.assertEqual(cfg_custom.effective_timeout, 15.0)

        cfg_zero = BonsaiNormalizerConfig(timeout_seconds=0.0)
        self.assertEqual(cfg_zero.effective_timeout, 12.0)

    def test_from_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({
                "enabled": True,
                "endpoint_url": "http://127.0.0.1:18091",
                "timeout_seconds": 14.0,
                "model": DEFAULT_MODEL,
                "revision": DEFAULT_REVISION,
            }, f)
            cfg_path = f.name

        try:
            cfg = BonsaiNormalizerConfig.from_file(cfg_path)
            self.assertTrue(cfg.enabled)
            self.assertEqual(cfg.endpoint_url, "http://127.0.0.1:18091")
            self.assertEqual(cfg.model, DEFAULT_MODEL)
            self.assertEqual(cfg.revision, DEFAULT_REVISION)
            self.assertEqual(cfg.effective_timeout, 14.0)
        finally:
            os.remove(cfg_path)


class TestBonsaiTokenHandling(unittest.TestCase):
    def test_token_file_stripped(self):
        with tempfile.NamedTemporaryFile("w", suffix=".token", delete=False) as f:
            f.write("  secret_token_123\n\n")
            token_path = f.name

        try:
            cfg = BonsaiNormalizerConfig(token_file=token_path)
            normalizer = BonsaiNormalizer(cfg)
            self.assertEqual(normalizer._read_bearer_token(), "secret_token_123")
        finally:
            os.remove(token_path)

    def test_empty_token_file_does_not_use_inline_fallback(self):
        with patch("builtins.open", unittest.mock.mock_open(read_data=" \n")):
            normalizer = BonsaiNormalizer(BonsaiNormalizerConfig(token_file="unused.token", token="inline"))
            self.assertIsNone(normalizer._read_bearer_token())

    def test_token_inline(self):
        cfg = BonsaiNormalizerConfig(token="  inline_token_abc  ")
        normalizer = BonsaiNormalizer(cfg)
        self.assertEqual(normalizer._read_bearer_token(), "inline_token_abc")

    def test_missing_token_file_returns_none(self):
        cfg = BonsaiNormalizerConfig(token_file="/nonexistent/path/bonsai.token")
        normalizer = BonsaiNormalizer(cfg)
        self.assertIsNone(normalizer._read_bearer_token())


class TestBonsaiNormalizerBypass(unittest.TestCase):
    def test_disabled_by_config(self):
        cfg = BonsaiNormalizerConfig(enabled=False)
        normalizer = BonsaiNormalizer(cfg)
        source = "не удаляй базу данных"
        result, meta = normalizer.normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta["status"], "bypassed")
        self.assertEqual(meta["reason"], "disabled_by_config")
        self.assertEqual(meta["latency_ms"], 0.0)

    def test_empty_or_whitespace_input(self):
        normalizer = BonsaiNormalizer()
        for empty_text in ("", "   ", "\n\t"):
            result, meta = normalizer.normalize(empty_text)
            self.assertEqual(result, empty_text)
            self.assertEqual(meta["status"], "bypassed")
            self.assertEqual(meta["reason"], "empty_input")

    def test_input_too_long_guarded(self):
        normalizer = BonsaiNormalizer()
        long_input = "слово " * 1201  # > 6000 chars
        self.assertGreater(len(long_input), 6000)
        result, meta = normalizer.normalize(long_input)
        self.assertEqual(result, long_input)
        self.assertEqual(meta["status"], "fallback")
        self.assertEqual(meta["reason"], "input_length_exceeded")


class TestBonsaiNormalizerSuccessAndPayload(unittest.TestCase):
    @patch("urllib.request.OpenerDirector.open")
    def test_successful_normalization(self, mock_open):
        source = "ну короче блин сделай бэкап базы данных на steamdeck в 12:00"
        candidate = "Сделай бэкап базы данных на steamdeck в 12:00."
        mock_open.return_value = _make_mock_response(candidate)

        normalizer = BonsaiNormalizer()
        result, meta = normalizer.normalize(source)

        self.assertEqual(result, candidate)
        self.assertEqual(meta["status"], "applied")
        self.assertIsNone(meta["reason"])
        self.assertGreater(meta["latency_ms"], 0.0)
        self.assertEqual(meta["model"], DEFAULT_MODEL)
        self.assertEqual(meta["revision"], DEFAULT_REVISION)

        # Verify request payload
        self.assertEqual(mock_open.call_count, 1)
        req = mock_open.call_args[0][0]
        self.assertEqual(req.full_url, "http://127.0.0.1:18091/v1/chat/completions")
        sent_body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(sent_body["model"], DEFAULT_MODEL)
        self.assertEqual(sent_body["temperature"], 0.0)
        self.assertEqual(sent_body["top_p"], 0.8)
        self.assertEqual(sent_body["top_k"], 20)
        self.assertEqual(sent_body["min_p"], 0.0)
        self.assertEqual(sent_body["presence_penalty"], 0.0)
        self.assertEqual(sent_body["repetition_penalty"], 1.0)
        self.assertEqual(sent_body["seed"], 42)
        self.assertEqual(sent_body["max_tokens"], 1024)
        self.assertFalse(sent_body["stream"])
        self.assertEqual(len(sent_body["messages"]), 2)
        self.assertEqual(sent_body["messages"][0], {"role": "system", "content": SYSTEM_PROMPT})
        self.assertEqual(sent_body["messages"][1]["content"], source)


class TestBonsaiNormalizerNetworkAndProtocolFailures(unittest.TestCase):
    @patch("urllib.request.OpenerDirector.open")
    def test_http_error(self, mock_open):
        mock_open.side_effect = urllib.error.HTTPError(
            url="http://127.0.0.1:18091/v1/chat/completions",
            code=503,
            msg="Service Unavailable",
            hdrs={},
            fp=io.BytesIO(b"error"),
        )
        normalizer = BonsaiNormalizer()
        source = "проверь статус"
        result, meta = normalizer.normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta["status"], "fallback")
        self.assertEqual(meta["reason"], "http_error_503")

    @patch("urllib.request.OpenerDirector.open")
    def test_timeout_error(self, mock_open):
        mock_open.side_effect = TimeoutError("Connection timed out")
        normalizer = BonsaiNormalizer()
        source = "проверь статус"
        result, meta = normalizer.normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta["status"], "fallback")
        self.assertEqual(meta["reason"], "timeout")

    @patch("urllib.request.OpenerDirector.open")
    def test_invalid_json(self, mock_open):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"<html>502 Bad Gateway</html>"
        mock_resp.__enter__.return_value = mock_resp
        mock_open.return_value = mock_resp

        normalizer = BonsaiNormalizer()
        source = "проверь статус"
        result, meta = normalizer.normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta["status"], "fallback")
        self.assertEqual(meta["reason"], "invalid_json_response")

    @patch("urllib.request.OpenerDirector.open")
    def test_finish_reason_not_stop(self, mock_open):
        mock_open.return_value = _make_mock_response("Отрезанный текст", finish_reason="length")
        normalizer = BonsaiNormalizer()
        source = "проверь статус"
        result, meta = normalizer.normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta["status"], "fallback")
        self.assertEqual(meta["reason"], "finish_reason_length")

    @patch("urllib.request.OpenerDirector.open")
    def test_model_mismatch(self, mock_open):
        mock_open.return_value = _make_mock_response("Текст", model="wrong-model")
        normalizer = BonsaiNormalizer()
        source = "проверь статус"
        result, meta = normalizer.normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta["status"], "fallback")
        self.assertEqual(meta["reason"], "model_mismatch")

    @patch("urllib.request.OpenerDirector.open")
    def test_revision_mismatch(self, mock_open):
        mock_open.return_value = _make_mock_response("Текст", revision="1111111111111111111111111111111111111111")
        normalizer = BonsaiNormalizer()
        source = "проверь статус"
        result, meta = normalizer.normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta["status"], "fallback")
        self.assertEqual(meta["reason"], "revision_mismatch")

    @patch("urllib.request.OpenerDirector.open")
    def test_revision_missing(self, mock_open):
        resp = _make_mock_response("Текст")
        data = json.loads(resp.read().decode("utf-8"))
        data.pop("bonsai", None)
        resp.read.return_value = json.dumps(data).encode("utf-8")
        mock_open.return_value = resp

        normalizer = BonsaiNormalizer()
        source = "проверь статус"
        result, meta = normalizer.normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta["status"], "fallback")
        self.assertEqual(meta["reason"], "revision_missing")

    @patch("urllib.request.OpenerDirector.open")
    def test_invalid_content_type(self, mock_open):
        resp = _make_mock_response("Текст")
        data = json.loads(resp.read().decode("utf-8"))
        data["choices"][0]["message"]["content"] = 12345
        resp.read.return_value = json.dumps(data).encode("utf-8")
        mock_open.return_value = resp

        normalizer = BonsaiNormalizer()
        source = "проверь статус"
        result, meta = normalizer.normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta["status"], "fallback")
        self.assertEqual(meta["reason"], "invalid_content_type")


class TestBonsaiNormalizerValidationGuards(unittest.TestCase):
    @patch("urllib.request.OpenerDirector.open")
    def test_empty_candidate(self, mock_open):
        mock_open.return_value = _make_mock_response("   ")
        normalizer = BonsaiNormalizer()
        source = "проверь статус"
        result, meta = normalizer.normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta["status"], "fallback")
        self.assertEqual(meta["reason"], "empty_candidate")

    @patch("urllib.request.OpenerDirector.open")
    def test_growth_exceeded(self, mock_open):
        source = "короткий текст"
        ballooned = "очень длинный ответ " * 50
        mock_open.return_value = _make_mock_response(ballooned)
        normalizer = BonsaiNormalizer()
        result, meta = normalizer.normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta["status"], "fallback")
        self.assertEqual(meta["reason"], "validation_growth_exceeded")

    @patch("urllib.request.OpenerDirector.open")
    def test_word_growth_exceeded(self, mock_open):
        source = "слово " * 10
        ballooned = "слово " * 35
        mock_open.return_value = _make_mock_response(ballooned)
        normalizer = BonsaiNormalizer()
        result, meta = normalizer.normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta["status"], "fallback")
        self.assertEqual(meta["reason"], "validation_growth_exceeded")

    @patch("urllib.request.OpenerDirector.open")
    def test_numeric_token_missing(self, mock_open):
        source = "сервер на порту 8091 упал"
        candidate = "Сервер на порту упал."  # 8091 dropped!
        mock_open.return_value = _make_mock_response(candidate)
        normalizer = BonsaiNormalizer()
        result, meta = normalizer.normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta["status"], "fallback")
        self.assertEqual(meta["reason"], "validation_numeric_missing")

    @patch("urllib.request.OpenerDirector.open")
    def test_numeric_token_added(self, mock_open):
        source = "проверь сервер"
        candidate = "Проверь сервер 1 раз."  # 1 added!
        mock_open.return_value = _make_mock_response(candidate)
        normalizer = BonsaiNormalizer()
        result, meta = normalizer.normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta["status"], "fallback")
        self.assertEqual(meta["reason"], "validation_numeric_added")

    @patch("urllib.request.OpenerDirector.open")
    def test_latin_identifier_missing(self, mock_open):
        source = "отправь отчет в Slack"
        candidate = "Отправь отчет в мессенджер."  # Slack dropped!
        mock_open.return_value = _make_mock_response(candidate)
        normalizer = BonsaiNormalizer()
        result, meta = normalizer.normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta["status"], "fallback")
        self.assertEqual(meta["reason"], "validation_latin_missing")

    @patch("urllib.request.OpenerDirector.open")
    def test_latin_identifier_added(self, mock_open):
        source = "отправь отчет коллегам"
        candidate = "Notes: Отправь отчет коллегам."  # "Notes" added!
        mock_open.return_value = _make_mock_response(candidate)
        normalizer = BonsaiNormalizer()
        result, meta = normalizer.normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta["status"], "fallback")
        self.assertEqual(meta["reason"], "validation_latin_added")

    @patch("urllib.request.OpenerDirector.open")
    def test_negation_loss_russian(self, mock_open):
        source = "не удаляй файл конфигурации"
        candidate = "Удаляй файл конфигурации."  # "не" dropped!
        mock_open.return_value = _make_mock_response(candidate)
        normalizer = BonsaiNormalizer()
        result, meta = normalizer.normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta["status"], "fallback")
        self.assertEqual(meta["reason"], "validation_negation_lost")

    @patch("urllib.request.OpenerDirector.open")
    def test_negation_loss_english(self, mock_open):
        source = "do not touch production database"
        candidate = "Touch production database."  # "not" dropped!
        mock_open.return_value = _make_mock_response(candidate)
        normalizer = BonsaiNormalizer()
        result, meta = normalizer.normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta["status"], "fallback")
        self.assertEqual(meta["reason"], "validation_negation_lost")


class TestExtractionHelpers(unittest.TestCase):
    def test_extract_numeric_tokens(self):
        text = "Значения 42, 3.14 и 1,000 с датой 2026-10-21"
        nums = extract_numeric_tokens(text)
        self.assertIn("42", nums)
        self.assertIn("3.14", nums)
        self.assertIn("1.000", nums)
        self.assertIn("2026", nums)
        self.assertIn("10", nums)
        self.assertIn("21", nums)

    def test_extract_latin_identifiers(self):
        text = "Сервис SteamDeck на Tailscale использует API v1 и Git_Hub"
        latins = extract_latin_identifiers(text)
        self.assertEqual(latins, {"steamdeck": 1, "tailscale": 1, "api": 1, "v1": 1, "git_hub": 1})

    def test_count_negation_tokens(self):
        self.assertEqual(count_negation_tokens("я ничего не знаю и никуда не пойду"), 4)
        self.assertEqual(count_negation_tokens("it isn't working and I don't know"), 2)
        self.assertEqual(count_negation_tokens("all systems operational"), 0)


class TestGetBonsaiNormalizerFactory(unittest.TestCase):
    def test_unset_env_returns_none(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(get_bonsai_normalizer())

    def test_nonexistent_file_returns_none(self):
        with patch.dict(os.environ, {"BONSAI_NORMALIZER_CONFIG": "/path/does/not/exist.json"}):
            self.assertIsNone(get_bonsai_normalizer())

    def test_valid_config_file_returns_instance(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"enabled": True, "endpoint_url": "http://127.0.0.1:18091"}, f)
            cfg_path = f.name

        try:
            with patch.dict(os.environ, {"BONSAI_NORMALIZER_CONFIG": cfg_path}):
                normalizer = get_bonsai_normalizer()
                self.assertIsNotNone(normalizer)
                self.assertTrue(normalizer.enabled)
        finally:
            os.remove(cfg_path)

    def test_disabled_config_returns_none(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"enabled": False}, f)
            cfg_path = f.name

        try:
            with patch.dict(os.environ, {"BONSAI_NORMALIZER_CONFIG": cfg_path}):
                self.assertIsNone(get_bonsai_normalizer())
        finally:
            os.remove(cfg_path)


class TestLocalContractRegressions(unittest.TestCase):
    def test_configuration_rejects_unpinned_or_invalid_values(self):
        for overrides in (
            {"model": "other-model"}, {"revision": ""}, {"revision": "other-revision"},
            {"enabled": "false"}, {"max_input_chars": 6001}, {"max_input_chars": 0},
            {"max_tokens": 0}, {"max_tokens": 1025}, {"max_tokens": True},
            {"temperature": 0.7}, {"temperature": math.nan},
            {"timeout_seconds": math.inf}, {"max_timeout_seconds": math.nan},
            {"top_p": math.nan}, {"top_p": 1.1}, {"top_k": -1},
            {"min_p": -0.1}, {"repetition_penalty": 0},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                BonsaiNormalizerConfig.from_dict(overrides)
        with self.assertRaises(ValueError):
            BonsaiNormalizerConfig(model="other-model")

    def test_timeout_is_always_finite_and_at_least_point_one(self):
        self.assertEqual(BonsaiNormalizerConfig(max_timeout_seconds=0.01).effective_timeout, 0.1)

    @patch("urllib.request.OpenerDirector.open")
    def test_unreadable_or_empty_configured_token_never_sends_transcript(self, mock_open):
        for token_value in (None, " \n"):
            normalizer = BonsaiNormalizer(BonsaiNormalizerConfig(token_file="unused.token"))
            with self.subTest(token_value=token_value), patch.object(
                normalizer, "_read_bearer_token", return_value=token_value
            ):
                source = "личный текст"
                result, meta = normalizer.normalize(source)
                self.assertEqual(result, source)
                self.assertEqual(meta["reason"], "token_unavailable")
                self.assertEqual(meta["status"], "fallback")
        mock_open.assert_not_called()

    @patch("urllib.request.OpenerDirector.open")
    def test_finish_reason_cannot_leak_upstream_content(self, mock_open):
        secret = "private transcript and secret_token"
        mock_open.return_value = _make_mock_response("текст", finish_reason=secret)
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            result, meta = BonsaiNormalizer().normalize("проверь статус")
        self.assertEqual(result, "проверь статус")
        self.assertEqual(meta["reason"], "finish_reason_invalid")
        self.assertNotIn(secret, json.dumps(meta) + output.getvalue())

    @patch("urllib.request.OpenerDirector.open")
    def test_repeated_numbers_and_identifiers_and_signed_quantity(self, mock_open):
        cases = (
            ("открой 2 файла и еще 2 файла", "Открой 2 файла.", "validation_numeric_missing"),
            ("открой 2 файла", "Открой 2 файла и еще 2 файла.", "validation_numeric_added"),
            ("SteamDeck и SteamDeck доступны", "SteamDeck доступен.", "validation_latin_missing"),
            ("SteamDeck доступен", "SteamDeck и SteamDeck доступны.", "validation_latin_added"),
            ("температура -5 градусов", "Температура 5 градусов.", "validation_numeric_missing"),
            ("температура −5 градусов", "Температура 5 градусов.", "validation_numeric_missing"),
            ("очередь 2-5", "Очередь 25.", "validation_numeric_missing"),
            ("сделай резервную копию", "Не сделай резервную копию.", "validation_negation_added"),
            ("Кажется, сервер не готов", "Сервер не готов.", "validation_qualifier_lost"),
            ("Если сервер готов, запусти", "Запусти, если-то сервер готов.", "validation_qualifier_lost"),
        )
        for source, candidate, reason in cases:
            with self.subTest(source=source, candidate=candidate):
                mock_open.return_value = _make_mock_response(candidate)
                result, meta = BonsaiNormalizer().normalize(source)
                self.assertEqual(result, source)
                self.assertEqual(meta["reason"], reason)
                self.assertEqual(meta["status"], "fallback")

    @patch("urllib.request.OpenerDirector.open")
    def test_response_body_has_a_finite_read_bound(self, mock_open):
        response = _make_mock_response("текст")
        response.read.return_value = b" " * (64 * 1024 + 1)
        mock_open.return_value = response
        source = "текст"
        result, meta = BonsaiNormalizer().normalize(source)
        response.read.assert_called_once_with(64 * 1024 + 1)
        self.assertEqual(result, source)
        self.assertEqual(meta["reason"], "response_too_large")

    def test_redirects_are_rejected_without_another_request(self):
        normalizer = BonsaiNormalizer()
        handler = next(h for h in normalizer._opener.handlers
                       if isinstance(h, urllib.request.HTTPRedirectHandler))
        request = urllib.request.Request("http://127.0.0.1:18091/v1/chat/completions")
        with self.assertRaises(urllib.error.HTTPError):
            handler.redirect_request(request, None, 307, "redirect", {}, "https://elsewhere.test/")

    @patch("urllib.request.OpenerDirector.open")
    def test_negation_scope_reversal_falls_back(self, mock_open):
        # Same counts, but moving "не" violates ordered copying.
        source = "Не удаляй базу, перезапусти сервер."
        candidate = "Удаляй базу, не перезапусти сервер."
        mock_open.return_value = _make_mock_response(candidate)
        result, meta = BonsaiNormalizer().normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta["status"], "fallback")
        self.assertEqual(meta["reason"], "validation_word_order_changed")

    @patch("urllib.request.OpenerDirector.open")
    def test_substitution_addition_and_reordering_fall_back(self, mock_open):
        cases = (
            ("Сначала проверь логи, потом перезапусти сервер.",
             "Потом перезапусти сервер, сначала проверь логи."),
            ("Анна передала отчёт Борису.", "Борису передала отчёт Анна."),
            ("Анна передала отчёт Борису.", "Анна передала отчёт Ивану."),
            ("Один пакет весит 2 кг, другой 3 г.", "Один пакет весит 2 г, другой 3 кг."),
            ("Первый сервер: 2, второй сервер: 3.", "Первый сервер: 3, второй сервер: 2."),
            ("Проверь Slack, затем Telegram.", "Проверь Telegram, затем Slack."),
            ("Do not delete data, restart service.", "Delete data, do not restart service."),
            ("Не удаляй базу.", "Не удаляй базу, перезапусти сервер."),
            ("Что происходит с сервером?", "С сервером всё хорошо."),
            ("Проверь сервер.", "Проверь сервер сервер."),
            ("Проверь сервер.", "."),
        )
        for source, candidate in cases:
            with self.subTest(source=source, candidate=candidate):
                mock_open.return_value = _make_mock_response(candidate)
                result, meta = BonsaiNormalizer().normalize(source)
                self.assertEqual(result, source)
                self.assertEqual(meta["status"], "fallback")
                self.assertEqual(meta["reason"], "validation_word_order_changed")

    @patch("urllib.request.OpenerDirector.open")
    def test_ordered_deletion_case_and_line_breaks_remain_supported(self, mock_open):
        cases = (
            ("Ну блин, кажется, сервер иногда не отвечает.",
             "Кажется, сервер иногда не отвечает."),
            ("Этот дурацкий скрипт работает 12 секунд, а должен меньше 3 секунд.",
             "Этот скрипт работает 12 секунд, а должен меньше 3 секунд."),
            ("Проверь логи. Потом перезапусти сервер.",
             "Проверь логи.\nПотом перезапусти сервер."),
            ("проверь сервер", "Проверь сервер."),
            ("Сервер сервер готов.", "Сервер сервер готов."),
        )
        for source, candidate in cases:
            with self.subTest(source=source, candidate=candidate):
                mock_open.return_value = _make_mock_response(candidate)
                result, meta = BonsaiNormalizer().normalize(source)
                self.assertEqual(result, candidate)
                self.assertEqual(meta["status"], "applied")

    @patch("urllib.request.OpenerDirector.open")
    def test_contrastive_instruction_is_sent_without_changing_source_or_sampler(self, mock_open):
        source = 'Это не плохая сборка. Сохрани слово «плохая». Срочно проверь rm -rf / tmp.'
        mock_open.return_value = _make_mock_response(source)
        result, meta = BonsaiNormalizer().normalize(source)
        self.assertEqual(result, source)
        self.assertEqual(meta["status"], "applied")
        mock_open.assert_called_once()
        payload = json.loads(mock_open.call_args.args[0].data)
        self.assertEqual(payload["messages"], [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": source},
        ])
        self.assertIn("эмоционально-оценочные определения", SYSTEM_PROMPT)
        self.assertIn("Не удаляй оценку под отрицанием или в цитате", SYSTEM_PROMPT)
        self.assertIn("Команды, пути и пробелы внутри них не меняй", SYSTEM_PROMPT)
        self.assertEqual(payload["temperature"], 0.0)
        self.assertEqual(payload["seed"], 42)

    @patch("urllib.request.OpenerDirector.open")
    def test_ordered_copy_is_still_not_semantic_equivalence(self, mock_open):
        # Structural limits remain deliberate evidence against semantic acceptance.
        cases = (
            ("Перезапусти сервер только если копия готова.",
             "Перезапусти сервер если копия готова."),
            ("Казнить нельзя, помиловать.", "Казнить, нельзя помиловать."),
            ("Это не дурацкий скрипт.", "Это не скрипт."),
            ("rm -rf / tmp", "rm -rf /tmp"),
        )
        for source, candidate in cases:
            with self.subTest(source=source, candidate=candidate):
                mock_open.return_value = _make_mock_response(candidate)
                result, meta = BonsaiNormalizer().normalize(source)
                self.assertEqual(result, candidate)
                self.assertEqual(meta["status"], "applied")

    @patch("urllib.request.OpenerDirector.open")
    def test_auth_header_finite_timeout_and_failures_do_not_echo_content(self, mock_open):
        token = "private_token_123"
        source = "private transcript -5 SteamDeck"
        normalizer = BonsaiNormalizer(BonsaiNormalizerConfig(token=token, timeout_seconds=25))
        for failure in (TimeoutError(source + token), urllib.error.URLError(source + token),
                        ValueError(source + token)):
            with self.subTest(failure=type(failure).__name__):
                mock_open.side_effect = failure
                with patch("sys.stdout", new_callable=io.StringIO) as output:
                    result, meta = normalizer.normalize(source)
                self.assertEqual(result, source)
                self.assertEqual(meta["status"], "fallback")
                self.assertNotIn(source, json.dumps(meta) + output.getvalue())
                self.assertNotIn(token, json.dumps(meta) + output.getvalue())
                request = mock_open.call_args.args[0]
                self.assertEqual(request.get_header("Authorization"), "Bearer " + token)
                self.assertEqual(mock_open.call_args.kwargs["timeout"], 20.0)
        self.assertEqual(mock_open.call_count, 3)  # One attempt per call, no retries.

    @patch("urllib.request.OpenerDirector.open")
    def test_invalid_response_shapes_and_utf8_fall_back(self, mock_open):
        for body in (b"[]", b"null", b"{}", b'{"choices": [null]}',
                     b'{"choices": [{"message": {}}]}', b"\xff"):
            with self.subTest(body=body):
                response = MagicMock()
                response.__enter__.return_value = response
                response.read.return_value = body
                mock_open.return_value = response
                result, meta = BonsaiNormalizer().normalize("исходный текст")
                self.assertEqual(result, "исходный текст")
                self.assertEqual(meta["status"], "fallback")

    @patch("urllib.request.OpenerDirector.open")
    def test_escaped_lone_surrogate_falls_back_before_serialization(self, mock_open):
        source = "Проверь сервер."
        for surrogate in ("\ud800", "\udfff"):
            with self.subTest(codepoint=ord(surrogate)):
                mock_open.return_value = _make_mock_response(source + surrogate)
                result, meta = BonsaiNormalizer().normalize(source)
                self.assertEqual(result, source)
                self.assertEqual(meta["status"], "fallback")
                self.assertEqual(meta["reason"], "invalid_content_encoding")
                result.encode("utf-8")

    def test_invalid_config_factory_is_content_free_and_never_opens_http(self):
        body = json.dumps({"model": "private transcript and token"})
        with patch("os.path.isfile", return_value=True), patch(
            "builtins.open", unittest.mock.mock_open(read_data=body)
        ), patch("sys.stdout", new_callable=io.StringIO) as output, patch(
            "urllib.request.OpenerDirector.open"
        ) as network:
            self.assertIsNone(get_bonsai_normalizer("unused.json"))
            self.assertIn("config_load_error", output.getvalue())
            self.assertNotIn("private transcript", output.getvalue())
            network.assert_not_called()

    def test_example_and_runbook_use_effective_configuration(self):
        example = json.loads((ROOT / "normalizer_config.example.json").read_text())
        runbook = (ROOT / "runbook.md").read_text()
        block = runbook.split("```json\n", 1)[1].split("```", 1)[0]
        self.assertEqual(json.loads(block), example)
        cfg = BonsaiNormalizerConfig.from_dict(example)
        self.assertEqual(cfg.temperature, 0.0)
        self.assertEqual(cfg.model, DEFAULT_MODEL)
        self.assertEqual(cfg.revision, DEFAULT_REVISION)


if __name__ == "__main__":
    unittest.main()
