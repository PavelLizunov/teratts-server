import copy
import unittest

import mac_translation_service as translation


class Engine:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def send(self, body):
        self.calls.append(body)
        return self.answer


class TranslationTests(unittest.TestCase):
    def payload(self):
        return dict(model=translation.MODEL_ID, stream=False, temperature=0, max_tokens=4096,
                    messages=[dict(role='system', content=translation.SYSTEM_PROMPT),
                              dict(role='user', content='Do not stop the server.')])

    def test_source_and_fixed_contract(self):
        payload = self.payload()
        self.assertEqual(translation.source_text(payload), 'Do not stop the server.')
        for field, value in [('model', 'other'), ('stream', True), ('max_tokens', 512), ('temperature', True), ('tools', [])]:
            invalid = copy.deepcopy(payload)
            invalid[field] = value
            with self.assertRaises(ValueError):
                translation.source_text(invalid)
        for text in ['', ' ', 'a'*2401, '\0', '\x85']:
            invalid = copy.deepcopy(payload)
            invalid['messages'][1]['content'] = text
            with self.assertRaises(ValueError):
                translation.source_text(invalid)
        payload['messages'][0]['content'] = 'Rewrite instead'
        with self.assertRaises(ValueError):
            translation.source_text(payload)

    def test_single_native_call_and_final_only(self):
        engine = Engine(dict(content='Не останавливайте сервер.', finish_reason='stop', reasoning='private', tool_calls=[]))
        result = translation.translate(engine, 'native-alias', 'Do not stop the server.')
        self.assertEqual(result['choices'][0]['message']['content'], 'Не останавливайте сервер.')
        self.assertNotIn('reasoning', str(result))
        self.assertEqual(len(engine.calls), 1)
        self.assertEqual(engine.calls[0]['model'], 'native-alias')
        self.assertEqual(engine.calls[0]['messages'][1]['content'], 'Do not stop the server.')

    def test_invalid_final_never_falls_back(self):
        for content, reason, tools in [('Не', 'length', []), ('Hello', 'stop', []),
                                      ('', 'stop', []), ('<think>Да</think>', 'stop', []),
                                      ('я'*2401, 'stop', []), ('Привет', 'stop', ['tool'])]:
            engine = Engine(dict(content=content, finish_reason=reason, tool_calls=tools))
            with self.assertRaises(ValueError):
                translation.translate(engine, 'native-alias', 'Hello')
            self.assertEqual(len(engine.calls), 1)


if __name__ == '__main__':
    unittest.main()
