"""Finite source-owned cleanup regressions; no native model requests."""
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from frognano_normalizer import FrogNanoNormalizer, FROGNANO_MODEL, FROGNANO_REVISION


def response(text):
    return io.BytesIO(json.dumps({'model': FROGNANO_MODEL, 'revision': FROGNANO_REVISION,
        'choices': [{'finish_reason': 'stop', 'message': {'content': text}}]}).encode())


class CleanupRegression(unittest.TestCase):
    def edit(self, source, native=None):
        with patch('urllib.request.OpenerDirector.open', return_value=response(source if native is None else native)) as opened:
            text, meta = FrogNanoNormalizer().normalize(source)
        opened.assert_called_once()
        return text, meta

    def test_missed_interjections_are_removed_even_with_unchanged_model(self):
        cases = [
            ('Блять, проверь журнал 56.', 'проверь журнал 56.'),
            ('Да, блядь, сохрани отчёт.', 'Да, сохрани отчёт.'),
            ('Отправь ответ, блять, сука.', 'Отправь ответ.'),
            ('Проверь, нахуй, endpoint.', 'Проверь, endpoint.'),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                actual, meta = self.edit(source)
                self.assertEqual(actual, expected)
                self.assertEqual(meta['status'], 'applied')

    def test_predicate_is_neutralized_not_deleted(self):
        for word, neutral in [('заебался', 'устал'), ('заебалась', 'устала'), ('заебались', 'устали')]:
            source = f'Я уже {word} это проверять. Не понимаю причину.'
            actual, meta = self.edit(source)
            self.assertEqual(actual, source.replace(word, neutral))
            self.assertEqual(meta['status'], 'applied')

    def test_demonstrative_object_survives_without_insult(self):
        source = 'Я уже заебался это говно тестировать. Комбинация не работает.'
        self.assertEqual(self.edit(source)[0], 'Я уже устал это тестировать. Комбинация не работает.')

    def test_exhaustion_does_not_erase_separate_nominal_predicate(self):
        for source in ['Я заебался, а это говно.', 'Я заебался — это говно.',
                       'Я заебался — это говно собачье.']:
            with self.subTest(source=source):
                self.assertEqual(self.edit(source)[0], source.replace('заебался', 'устал'))

    def test_model_deletion_of_content_is_rejected_exactly(self):
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
        self.assertEqual(self.edit(source)[0], 'сохрани «сука, не меняй порядок». Затем позвони Анне.')

    def test_quote_literal_and_technical_shields(self):
        cases = [
            'Сохрани слово блять в словаре.',
            'Сука родила щенков.',
            'В анализе нашли говно.',
            'Это говно, а не инструмент.',
            'Путь /tmp/блять.txt не меняй.',
            'Открой https://example.test/блять и файл блять.txt.',
            'Сохрани `блять` и «он сказал “сука”».',
            'Сохрани "Он сказал "блять", затем ушёл".',
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
            'Блять! Проверь журнал.',
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

    def test_control_and_question_punctuation_cannot_move(self):
        source = 'Блять, казнить нельзя, помиловать?'
        for native in ['казнить, нельзя помиловать?', 'казнить нельзя, помиловать.']:
            with self.subTest(native=native):
                self.assertEqual(self.edit(source, native)[0], source)

    def test_supported_native_deletion_accepts_adjacent_comma_variants(self):
        source = 'Да, блять, проверь это. Я уже заебался ждать.'
        for native in ['Да, проверь это. Я уже заебался ждать.',
                       'Да проверь это. Я уже заебался ждать.']:
            with self.subTest(native=native):
                self.assertEqual(self.edit(source, native)[0], 'Да, проверь это. Я уже устал ждать.')

    def test_comma_before_condition_is_not_owned_by_interjection(self):
        source = 'Не запускай вообще, блять, если копия не готова.'
        self.assertEqual(self.edit(source)[0], 'Не запускай вообще, если копия не готова.')

    def test_exact_source_slices_survive_rendering(self):
        source = 'Блять, сохрани /tmp/a\t  и 42.\r\nНе меняй «А  Б».  '
        text, _ = self.edit(source)
        self.assertEqual(text.encode(), source.removeprefix('Блять, ').encode())

    def test_all_profanity_does_not_produce_empty_success(self):
        source = 'Блять, сука.'
        text, meta = self.edit(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['status'], 'fallback')

    def test_failure_never_runs_local_cleanup_or_retries(self):
        source = 'Блять, сохрани отчёт.  \r\n'
        with patch('urllib.request.OpenerDirector.open', side_effect=TimeoutError) as opened:
            text, meta = FrogNanoNormalizer().normalize(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['reason'], 'timeout')
        opened.assert_called_once()

    def test_bypass_and_rejected_native_never_apply_local_edits(self):
        from frognano_normalizer import FrogNanoNormalizerConfig
        source = 'Блять, не меняй порт 1279.  '
        for cfg in [FrogNanoNormalizerConfig(enabled=False), FrogNanoNormalizerConfig(max_input_chars=2)]:
            with self.subTest(cfg=cfg), patch('urllib.request.OpenerDirector.open') as opened:
                text, meta = FrogNanoNormalizer(cfg).normalize(source)
                self.assertEqual(text, source)
                self.assertNotEqual(meta['status'], 'applied')
                opened.assert_not_called()
        for native in ['Блять, меняй порт 1279.', 'Блять, не меняй порт 1280.',
                       '<think>думай</think>' + source]:
            with self.subTest(native=native):
                text, meta = self.edit(source, native)
                self.assertEqual(text, source)
                self.assertEqual(meta['status'], 'fallback')

    def test_repeated_spans_are_bounded_and_occurrence_owned(self):
        source = 'Блять, сохрани «блять». ' * 70
        actual, meta = self.edit(source)
        self.assertEqual(actual, 'сохрани «блять». ' * 70)
        self.assertEqual(meta['status'], 'applied')

    def test_neutral_unchanged_status_is_not_applied(self):
        source = 'Не меняй срок и endpoint.  '
        text, meta = self.edit(source)
        self.assertEqual(text, source)
        self.assertEqual(meta['status'], 'unchanged')


if __name__ == '__main__':
    unittest.main()
