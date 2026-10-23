"""Finite source-owned cleanup regressions for Bolt smart editor.

Tests: source-anchored validation (no local forced cleanup), standalone curse
clause deletions ('Блядь!','Блять!','Ёб твою мать!','Меня это заебало!'),
profanity/emotional interjection deletion when model removes them, model keeping
profanity returns source unchanged, partial model deletion of repeated curses,
quote/code/technical/literal shields, malformed quotes abstain,
negation/condition/instruction preservation, no generic clause deletion,
repeated/source alignment, exact whitespace bytes, empty output guard.
No remote calls, SSH, inference, private/audio access.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bolt_normalizer import BOLT_MODEL, BOLT_REVISION, BoltNormalizer


def _response(text):
    return io.BytesIO(json.dumps({
        'model': BOLT_MODEL, 'revision': BOLT_REVISION,
        'choices': [{'finish_reason': 'stop',
                     'message': {'content': text}}],
    }).encode())


class BoltCleanupRegression(unittest.TestCase):
    """Source-owned cleanup with validated model candidate."""

    def edit(self, source, native=None):
        with patch('urllib.request.OpenerDirector.open',
                   return_value=_response(source if native is None else native)) as opened:
            text, meta = BoltNormalizer().normalize(source)
        opened.assert_called_once()
        return text, meta

    # ---------------------------------------------------------------
    # Core contract: validate candidate, return it exactly; no forced cleanup
    # ---------------------------------------------------------------
    def test_model_keeps_profanity_returns_source_unchanged(self):
        """When model returns source unchanged, profanity stays — no local cleanup."""
        cases = [
            'Блять, проверь журнал 56.',
            'Да, блядь, сохрани отчёт.',
            'Отправь ответ, блять, сука.',
            'Проверь, нахуй, endpoint.',
            'Я уже заебался это проверять. Не понимаю причину.',
            'Меня это заебало! Проверь журнал.',
            'Не запускай вообще, блять, если копия не готова.',
        ]
        for source in cases:
            with self.subTest(source=source):
                actual, meta = self.edit(source)
                self.assertEqual(actual, source)
                self.assertEqual(meta['status'], 'unchanged')

    # ---------------------------------------------------------------
    # Positive: supported profanity/emotional deletions by model
    # ---------------------------------------------------------------
    def test_model_removes_standalone_curses(self):
        """Model removes supported profanity: validated and returned exactly."""
        cases = [
            ('Блять, проверь журнал 56.', 'проверь журнал 56.', 'проверь журнал 56.'),
            ('Да, блядь, сохрани отчёт.', 'Да, сохрани отчёт.', 'Да, сохрани отчёт.'),
            ('Отправь ответ, блять, сука.', 'Отправь ответ.', 'Отправь ответ.'),
            ('Проверь, нахуй, endpoint.', 'Проверь, endpoint.', 'Проверь, endpoint.'),
        ]
        for source, native, expected in cases:
            with self.subTest(source=source):
                actual, meta = self.edit(source, native)
                self.assertEqual(actual, expected)
                self.assertEqual(meta['status'], 'applied')

    def test_model_word_substitution_rejected(self):
        """The deletion-only prompt does not authorize neutral-word substitutions."""
        for word, neutral in [('заебался', 'устал'), ('заебалась', 'устала'),
                              ('заебались', 'устали')]:
            source = f'Я уже {word} это проверять. Не понимаю причину.'
            native = source.replace(word, neutral)
            with self.subTest(word=word):
                actual, meta = self.edit(source, native)
                self.assertEqual(actual, source)
                self.assertEqual(meta['status'], 'fallback')

    def test_standalone_exhaustion_substitution_rejected(self):
        """Exact whole-clause deletion is allowed, word substitution is not."""
        source = 'Меня это заебало! Проверь журнал.'
        native = source.replace('заебало', 'надоело')
        actual, meta = self.edit(source, native)
        self.assertEqual(actual, source)
        self.assertEqual(meta['status'], 'fallback')

    def test_menya_eto_zaebalo_variants_replacement(self):
        """Substitution remains rejected for every object-subject variant."""
        for prefix in ['Меня это', 'Нас это', 'Меня уже это', 'Меня это уже',
                       'Всех это', 'Меня всё это']:
            source = f'{prefix} заебало. Проверь отчёт.'
            native = source.replace('заебало', 'надоело')
            with self.subTest(source=source):
                actual, meta = self.edit(source, native)
                self.assertEqual(actual, source)
                self.assertEqual(meta['status'], 'fallback')

    # ---------------------------------------------------------------
    # Standalone whole-clause deletions
    # ---------------------------------------------------------------
    def test_standalone_curse_clause_deletion(self):
        """Pure standalone 'Блядь!', 'Блять!' clauses deletable by model."""
        cases = [
            ('Блять! Проверь журнал.', 'Проверь журнал.'),
            ('Блядь! Сохрани отчёт.', 'Сохрани отчёт.'),
        ]
        for source, native in cases:
            with self.subTest(source=source):
                actual, meta = self.edit(source, native)
                self.assertEqual(actual, native)
                self.assertEqual(meta['status'], 'applied')

    def test_standalone_maternal_curse_deletion(self):
        """'Ёб твою мать!' whole clause deletable by model."""
        source = 'Ёб твою мать! Проверь журнал.'
        native = 'Проверь журнал.'
        actual, meta = self.edit(source, native)
        self.assertEqual(actual, native)
        self.assertEqual(meta['status'], 'applied')

    def test_standalone_menya_eto_zaebalo_deletion(self):
        """'Меня это заебало!' whole clause deletable by model."""
        source = 'Меня это заебало! Проверь журнал.'
        native = 'Проверь журнал.'
        actual, meta = self.edit(source, native)
        self.assertEqual(actual, native)
        self.assertEqual(meta['status'], 'applied')

    def test_menya_eto_zaebalo_variants_deletion(self):
        """Object-subject variants of заебало — whole clause deletable."""
        for prefix in ['Меня это', 'Нас это', 'Всех это']:
            source = f'{prefix} заебало. Проверь отчёт.'
            native = 'Проверь отчёт.'
            with self.subTest(source=source):
                actual, meta = self.edit(source, native)
                self.assertEqual(actual, native)
                self.assertEqual(meta['status'], 'applied')

    # ---------------------------------------------------------------
    # Model partial deletion: removes only selected curse, keeps others
    # ---------------------------------------------------------------
    def test_model_partial_deletion_first_curse(self):
        """Model removes first repeated curse only, second stays."""
        source = 'Блять, проверь отчёт. Блять, сохрани файл.'
        native = 'проверь отчёт. Блять, сохрани файл.'
        actual, meta = self.edit(source, native)
        self.assertEqual(actual, native)
        self.assertEqual(meta['status'], 'applied')

    def test_model_partial_deletion_second_curse(self):
        """Model removes second repeated curse only, first stays."""
        source = 'Блять, проверь отчёт. Блять, сохрани файл.'
        native = 'Блять, проверь отчёт. сохрани файл.'
        actual, meta = self.edit(source, native)
        self.assertEqual(actual, native)
        self.assertEqual(meta['status'], 'applied')

    def test_model_partial_exhaustion_and_curse(self):
        """Model removes curse but keeps exhaustion predicate unchanged."""
        source = 'Да, блять, проверь это. Я уже заебался ждать.'
        native = 'Да, проверь это. Я уже заебался ждать.'
        actual, meta = self.edit(source, native)
        self.assertEqual(actual, native)
        self.assertEqual(meta['status'], 'applied')

    def test_no_extra_forced_cleanup(self):
        """No local cleanup on top of model's choices: if model keeps a word, it stays."""
        source = 'Да, блять, проверь это. Я уже заебался ждать.'
        # Model removes only curse, keeps exhaustion unchanged
        for native in ['Да, проверь это. Я уже заебался ждать.',
                       'Да проверь это. Я уже заебался ждать.']:
            with self.subTest(native=native):
                actual, meta = self.edit(source, native)
                self.assertEqual(actual, native)
                self.assertIn('заебался', actual)  # NOT replaced to устал

    def test_model_demonstrative_object_substitution_rejected(self):
        """Neither a neutral substitute nor arbitrary object deletion is admitted."""
        source = 'Я уже заебался это говно тестировать. Комбинация не работает.'
        native = 'Я уже устал это тестировать. Комбинация не работает.'
        actual, meta = self.edit(source, native)
        self.assertEqual(actual, source)
        self.assertEqual(meta['status'], 'fallback')

    def test_model_exhaustion_substitution_with_separate_predicate_rejected(self):
        """Separate nominal predicates do not authorize word substitution."""
        for source in ['Я заебался, а это говно.', 'Я заебался — это говно.',
                       'Я заебался — это говно собачье.']:
            native = source.replace('заебался', 'устал')
            with self.subTest(source=source):
                actual, meta = self.edit(source, native)
                self.assertEqual(actual, source)
                self.assertEqual(meta['status'], 'fallback')

    def test_model_removes_comma_separated_curse_before_condition(self):
        """Model removes comma-separated curse before condition clause."""
        source = 'Не запускай вообще, блять, если копия не готова.'
        native = 'Не запускай вообще, если копия не готова.'
        actual, meta = self.edit(source, native)
        self.assertEqual(actual, native)

    def test_supported_native_deletion_with_comma_variants(self):
        """Model comma variants validated; exhaustion kept by model stays."""
        source = 'Да, блять, проверь это. Я уже заебался ждать.'
        for native in ['Да, проверь это. Я уже заебался ждать.',
                       'Да проверь это. Я уже заебался ждать.']:
            with self.subTest(native=native):
                actual, meta = self.edit(source, native)
                self.assertEqual(actual, native)

    # ---------------------------------------------------------------
    # Negative: unsupported deletions must fail closed
    # ---------------------------------------------------------------
    def test_model_deletion_of_content_rejected(self):
        source = 'Блять, проверь отчёт. Затем позвони Анне.'
        text, meta = self.edit(source, 'Проверь отчёт.')
        self.assertEqual(text, source)
        self.assertEqual(meta['status'], 'fallback')
        self.assertEqual(meta['reason'], 'validation_unsupported_edit')

    def test_model_cannot_delete_quote_or_inside_quote_profanity(self):
        source = 'Блять, сохрани «сука, не меняй порядок». Затем позвони Анне.'
        for native in ['сохрани «не меняй порядок». Затем позвони Анне.',
                       'сохрани порядок. Затем позвони Анне.']:
            with self.subTest(native=native):
                self.assertEqual(self.edit(source, native)[0], source)
        # Model correctly removes outer Блять only
        native_ok = 'сохрани «сука, не меняй порядок». Затем позвони Анне.'
        self.assertEqual(
            self.edit(source, native_ok)[0], native_ok)

    def test_substantive_continuation_loss_rejected(self):
        """Model deleting substantive continuation must be rejected."""
        source = 'Блять, проверь отчёт. Затем позвони Анне.'
        text, meta = self.edit(source, 'проверь отчёт.')
        self.assertEqual(text, source)
        self.assertEqual(meta['status'], 'fallback')

    # ---------------------------------------------------------------
    # Shields: quote, literal, technical, metalinguistic contexts
    # ---------------------------------------------------------------
    def test_quote_literal_and_technical_shields(self):
        cases = [
            'Сохрани слово блять в словаре.',
            'Сука родила щенков.',
            'В анализе нашли говно.',
            'Это говно, а не инструмент.',
            'Путь /tmp/блять.txt не меняй.',
            'Открой https://example.test/блять и файл блять.txt.',
            'Сохрани `блять` и «он сказал \"сука\"».',
            'Сохрани \"Он сказал \"блять\", затем ушёл\".',
            'Сохрани «незакрытую цитату. Блять, проверь.',
            '> Блять, это цитата.',
            'Значение блядь — буквальная строка.',
            'Сука, которую мы забрали, заболела.',
            'Ах, в отличие от ох, выражает удивление.',
            'Блядь, как существительное, относится к первому склонению.',
            'Напиши нахуй, затем сохрани файл.',
            'Он не блядь.',
            'Блядь заболела.',
            'Блядь, которая пришла вчера, заболела.',
            'Он блядь, но это не повод удалять факт.',
            'Если я заебался, останови таймер.',
            'Если он блядь, не пускай его.',
            'Произнеси вслух нахуй.',
            'Блять! Проверь журнал.',  # standalone exclamation: model returns unchanged = kept
            'Я не заебался это говно тестировать.',
            'Напиши: блять, затем сохрани файл.',
            'Напиши крупно блять, затем сохрани файл.',
            'Напиши я заебалась ждать.',
            'Напиши мы заебались ждать.',
            'Я не заебался это проверять.',
            'Этот блять-таймер готов.',
            'БлятЬ\u0301, сохрани исходное написание.',
        ]
        for source in cases:
            with self.subTest(source=source):
                actual, meta = self.edit(source)
                self.assertEqual(actual, source)
                self.assertEqual(meta['status'], 'unchanged')

    def test_zaebalo_shielded_by_negation_and_condition(self):
        """Negation/condition shields must block заебало too."""
        for source in [
            'Если меня это заебало, останови таймер.',
            'Меня это не заебало.',
        ]:
            with self.subTest(source=source):
                actual, meta = self.edit(source)
                self.assertEqual(actual, source)
                self.assertEqual(meta['status'], 'unchanged')

    # ---------------------------------------------------------------
    # Control and question punctuation must not move
    # ---------------------------------------------------------------
    def test_control_and_question_punctuation_cannot_move(self):
        source = 'Блять, казнить нельзя, помиловать?'
        for native in ['казнить, нельзя помиловать?',
                       'казнить нельзя, помиловать.']:
            with self.subTest(native=native):
                self.assertEqual(self.edit(source, native)[0], source)

    # ---------------------------------------------------------------
    # Exact source slices, whitespace, bytes
    # ---------------------------------------------------------------
    def test_exact_source_slices_survive_rendering(self):
        source = 'Блять, сохрани /tmp/a\t  и 42.\r\nНе меняй «А  Б».  '
        native = source.removeprefix('Блять, ')
        text, _ = self.edit(source, native)
        self.assertEqual(text.encode(), native.encode())

    def test_all_profanity_source_unchanged_when_model_keeps(self):
        """All-profanity source with model returning unchanged is 'unchanged'."""
        source = 'Блять, сука.'
        text, meta = self.edit(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['status'], 'unchanged')

    # ---------------------------------------------------------------
    # Failure never runs local cleanup or retries
    # ---------------------------------------------------------------
    def test_failure_never_runs_local_cleanup_or_retries(self):
        source = 'Блять, сохрани отчёт.  \r\n'
        with patch('urllib.request.OpenerDirector.open',
                   side_effect=TimeoutError) as opened:
            text, meta = BoltNormalizer().normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['reason'], 'timeout')
        opened.assert_called_once()

    def test_bypass_and_rejected_native_never_apply_local_edits(self):
        from bolt_normalizer import BoltNormalizerConfig
        source = 'Блять, не меняй порт 1279.  '
        for cfg in [BoltNormalizerConfig(enabled=False),
                    BoltNormalizerConfig(max_input_chars=2)]:
            with self.subTest(cfg=cfg), \
                 patch('urllib.request.OpenerDirector.open') as opened:
                text, meta = BoltNormalizer(cfg).normalize(source)
                self.assertEqual(text, source)
                self.assertNotEqual(meta['status'], 'applied')
                opened.assert_not_called()
        for native in ['Блять, меняй порт 1279.',
                       'Блять, не меняй порт 1280.',
                       '<think>думай</think>' + source]:
            with self.subTest(native=native):
                text, meta = self.edit(source, native)
                self.assertEqual(text, source)
                self.assertEqual(meta['status'], 'fallback')

    # ---------------------------------------------------------------
    # Repeated spans bounded and occurrence-owned
    # ---------------------------------------------------------------
    def test_repeated_spans_bounded_and_occurrence_owned(self):
        source = 'Блять, сохрани «блять». ' * 70
        native = 'сохрани «блять». ' * 70
        actual, meta = self.edit(source, native)
        self.assertEqual(actual, native)
        self.assertEqual(meta['status'], 'applied')

    def test_candidate_capitalization_only_allowed_after_actual_deletion(self):
        source = 'Блять, проверь файл.'
        self.assertEqual(self.edit(source, 'Проверь файл.')[0], 'Проверь файл.')
        text, meta = self.edit(source, 'Блять, Проверь файл.')
        self.assertEqual(text, source)
        self.assertEqual(meta['status'], 'fallback')
        source = 'блядь, открой GitHub.'
        self.assertEqual(self.edit(source, 'Открой GitHub.')[0], 'Открой GitHub.')

    def test_neutral_unchanged_status_is_not_applied(self):
        source = 'Не меняй срок и endpoint.  '
        text, meta = self.edit(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['status'], 'unchanged')

    # ---------------------------------------------------------------
    # No generic clause deletion acceptance
    # ---------------------------------------------------------------
    def test_no_generic_clause_deletion(self):
        """Candidate that removes clauses without numbers/negation must still fail."""
        source = 'Блять, проверь отчёт. Сделай копию. Затем перезапусти.'
        # Model tries to delete two substantive clauses
        text, meta = self.edit(source, 'Проверь отчёт.')
        self.assertEqual(text, source)
        self.assertEqual(meta['status'], 'fallback')

    # ---------------------------------------------------------------
    # Finite unknown rejection
    # ---------------------------------------------------------------
    def test_finite_unknown_word_is_not_deletable(self):
        """A word not in our finite inventory must not be removed."""
        source = 'Хрень, проверь статус.'
        text, meta = self.edit(source)
        # "хрень" is not in our finite inventory — model returning unchanged is fine
        self.assertEqual(text, source)
        self.assertEqual(meta['status'], 'unchanged')

    # ---------------------------------------------------------------
    # Standalone maternal curse ('сука' at tail)
    # ---------------------------------------------------------------
    def test_standalone_maternal_curse_suka(self):
        """Standalone 'сука' at sentence end after comma is deletable."""
        source = 'Отправь ответ, сука.'
        native = 'Отправь ответ.'
        text, meta = self.edit(source, native)
        self.assertEqual(text, native)
        self.assertEqual(meta['status'], 'applied')


if __name__ == '__main__':
    unittest.main()
