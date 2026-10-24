"""Retained deletion-only utility tests; the rewrite client does not use it.

The owner superseded deletion-only editing. Exercise this legacy helper directly
rather than asserting obsolete restrictions against the paraphrasing client.
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bolt_cleanup import render_supported_bolt_cleanup
from bolt_normalizer import BoltNormalizer


class LegacyBoltCleanup(unittest.TestCase):
    def test_supported_source_owned_deletions_return_exact_candidate(self):
        cases = [
            ('Блять, проверь журнал 56.', 'проверь журнал 56.'),
            ('Да, блядь, сохрани отчёт.', 'Да, сохрани отчёт.'),
            ('Отправь ответ, блять, сука.', 'Отправь ответ.'),
            ('Ёб твою мать! Проверь журнал.', 'Проверь журнал.'),
            ('Меня это заебало! Проверь журнал.', 'Проверь журнал.'),
            ('Блять, проверь отчёт. Блять, сохрани файл.',
             'проверь отчёт. Блять, сохрани файл.'),
            ('Блять, сохрани /tmp/a\t  и 42.\r\nНе меняй «А  Б».  ',
             'сохрани /tmp/a\t  и 42.\r\nНе меняй «А  Б».  '),
        ]
        for source, candidate in cases:
            with self.subTest(source=source):
                self.assertEqual(render_supported_bolt_cleanup(source, candidate), candidate)

    def test_legacy_helper_keeps_its_own_restrictions(self):
        cases = [
            ('Я уже заебался это проверять.', 'Я уже устал это проверять.'),
            ('Блять, проверь отчёт. Затем позвони Анне.', 'Проверь отчёт.'),
            ('Блять, сохрани «сука, не меняй порядок».', 'сохрани «не меняй порядок».'),
            ('Сохрани «незакрытую цитату. Блять, проверь.', 'Сохрани цитату.'),
            ('Блять, проверь файл.', 'Блять, Проверь файл.'),
            ('Блять! /tmp/foo', '/Tmp/foo'),
            ('Блять, сука.', ''),
        ]
        for source, candidate in cases:
            with self.subTest(source=source), self.assertRaises(ValueError):
                render_supported_bolt_cleanup(source, candidate)

    def test_unchanged_source_is_not_locally_cleaned(self):
        for source in ('Блять, сука.', 'Если меня это заебало, останови таймер.',
                       'Сохрани `блять` и «он сказал сука».'):
            self.assertEqual(render_supported_bolt_cleanup(source, source), source)

    def test_rewrite_client_never_calls_legacy_validator(self):
        with patch('bolt_cleanup.render_supported_bolt_cleanup',
                   side_effect=AssertionError('obsolete lexical gate')) as legacy:
            candidate = 'Проверь настройки сервера.'
            self.assertEqual(BoltNormalizer()._render_candidate('Блядь, сервер проверь.', candidate), candidate)
            legacy.assert_not_called()


if __name__ == '__main__':
    unittest.main()
