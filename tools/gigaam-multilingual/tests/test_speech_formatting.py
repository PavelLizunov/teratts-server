import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from speech_formatting import Formatter, validate_format, words, contextual_english


class Tests(unittest.TestCase):
    def test_safe_punctuation(self):
        out, meta = Formatter(lambda text: ('Не, не удаляй 12 файлов, потом открой GitHub.', True))('не не удаляй 12 файлов потом открой GitHub')
        self.assertEqual(out, 'Не, не удаляй 12 файлов, потом открой GitHub.')
        self.assertEqual(meta['status'], 'applied')

    def test_reject_changes_truncation_and_instructions(self):
        source = 'не не удаляй 12 файлов'
        for candidate in ['Удаляй 12 файлов.', 'Не удаляй 12 файлов.', 'Два плюс два равно четыре.', '', '```text\nне не удаляй 12 файлов\n```']:
            self.assertFalse(validate_format(source, candidate))
            out, meta = Formatter(lambda text: (candidate, True))(source)
            self.assertEqual(words(out), words(source))
            self.assertEqual(meta['status'], 'fallback_preserved_words')
            self.assertEqual(meta['segments'][0]['candidate_text'], candidate)

    def test_failure_and_empty(self):
        def broken(text): raise TimeoutError()
        out, meta = Formatter(broken)('тест')
        self.assertEqual(out, 'Тест.')
        self.assertEqual(meta['segments'][0]['status'], 'failed')
        self.assertEqual(Formatter(broken)('')[0], '')
        out, meta = Formatter(lambda text: ('Другие слова', False))('тест')
        self.assertEqual(out, 'Тест.')

    def test_contextual_english_only(self):
        self.assertEqual(contextual_english('это английское выражение ор нот а не программа')[0], 'это английское выражение or not а не программа')
        for text in ['ор нот', 'это не английское выражение', 'ор нот и русский текст', 'https://test/ор-нот', '`ор нот`', '`английское выражение ор нот`', 'не английское выражение ор нот']:
            self.assertEqual(contextual_english(text)[0], text)

    def test_protect_english_identifiers_numbers(self):
        for source, candidate in [('открой GitHub','Открой Github.'), ('код foo_bar','Код foo-bar.'), ('12.3 и 15:30','12,3 и 15:30')]:
            self.assertFalse(validate_format(source, candidate))

    def test_projection_retains_punctuation_without_changed_words(self):
        source='потом проверь сервис он работает не не удаляй файл'
        generated='Потом проверь сервис. Он работает, не удаляй файл.'
        out,meta=Formatter(lambda text:(generated,True))(source)
        self.assertEqual(words(out),words(source))
        self.assertIn('сервис. Он работает',out)
        self.assertIn('не не',out)
        self.assertEqual(meta['status'],'fallback_preserved_words')

    def test_long_input_all_words_preserved(self):
        source = ' '.join(['слово']*130)
        out, meta = Formatter(lambda text: (text.capitalize()+'.', True))(source)
        self.assertEqual(words(source), words(out))
        self.assertEqual(len(meta['segments']), 3)
        self.assertEqual(meta['status'], 'applied')

if __name__=='__main__':unittest.main()
