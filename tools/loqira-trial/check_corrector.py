"""Focused transport/segmentation checks; no model-quality campaign."""
import unittest
from corrector import LoqiraCorrector, MODEL, SYSTEM


class Fake(LoqiraCorrector):
    def __init__(self, mode='ok'):
        super().__init__(lambda text: (text, {'status': 'preserved', 'input_text': text}))
        self.mode = mode
        self.generated = []

    def request(self, path, payload=None, timeout=20):
        if self.mode == 'unavailable':
            raise ConnectionError('offline')
        if path == '/apply-template':
            source = payload['messages'][1]['content']
            return {'prompt': '<|im_start|>system\n'+SYSTEM+'<|im_end|>\n<|im_start|>user\n'+source+'<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'}
        if path == '/tokenize':
            return {'tokens': [1] * len(payload['content'])}
        if path == '/v1/chat/completions':
            source = payload['messages'][1]['content']; self.generated.append(source)
            return {'model': MODEL, 'usage': {}, 'choices': [{'finish_reason': 'length' if self.mode == 'incomplete' else 'stop',
                    'message': {'content': source.replace('ошбка', 'ошибка')}}]}
        raise AssertionError(path)


class Checks(unittest.TestCase):
    def test_lexical_change_is_accepted(self):
        output, meta = Fake()('ошбка здесь')
        self.assertEqual(output, 'ошибка здесь')
        self.assertEqual(meta['status'], 'applied')

    def test_unavailable_fallback_preserves_input(self):
        output, meta = Fake('unavailable')('не удаляй backup.tar')
        self.assertEqual(output, 'не удаляй backup.tar')
        self.assertEqual(meta['status'], 'fallback_sage')
        self.assertIn('ConnectionError', meta['segments'][0]['reason'])

    def test_incomplete_candidate_is_retained_not_used(self):
        output, meta = Fake('incomplete')('ошбка здесь')
        self.assertEqual(output, 'ошбка здесь')
        self.assertEqual(meta['segments'][0]['candidate_text'], 'ошибка здесь')

    def test_split_covers_original_offsets(self):
        source = 'слово ' * 250
        engine = Fake(); output, meta = engine(source)
        self.assertGreater(len(meta['segments']), 1)
        self.assertEqual(output.split(), source.split())
        self.assertEqual(''.join(source[s['start']:s['end']] for s in meta['segments']), source)
        self.assertTrue(all(s['prompt_tokens'] <= 640 for s in meta['segments']))

    def test_overlong_unsplittable_falls_back(self):
        source = 'x'*900
        output, meta = Fake()(source)
        self.assertEqual(output, source)
        self.assertIn('unsplittable', meta['segments'][0]['reason'])


if __name__ == '__main__':
    unittest.main()
