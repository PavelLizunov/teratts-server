import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from corpus_review import summarize


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.joinpath('sentences.json').write_text(json.dumps([
            {'text': 'same'}, {'text': 'same'}, {'text': 'other'},
        ]))

    def receipt(self, indices, choices=None):
        choices = choices or ['suspect'] * len(indices)
        return {'indices': indices, 'response': {'answers': {
            str(i): {'choice': choice, 'probabilities': {'suspect': .51}}
            for i, choice in zip(indices, choices)
        }}}

    def save(self, receipts):
        self.root.joinpath('semantic-choice-answers.jsonl').write_text(
            '\n'.join(json.dumps(r) for r in receipts) + '\n')

    def summary(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return summarize(self.root)

    def test_partial_unique_coverage_and_all_nonclean_choices(self):
        self.save([self.receipt([0, 1], ['suspect', 'uncertain'])])
        summary = self.summary()
        self.assertEqual(summary['reviewed'], 2)
        self.assertEqual(summary['unique_texts_reviewed'], 1)
        self.assertEqual(summary['flagged_count'], 2)
        self.assertEqual(summary['high_suspect_count'], 0)
        self.assertFalse(summary['complete'])
        flags = json.loads(self.root.joinpath('semantic-flags.json').read_text())
        self.assertEqual([r['choice'] for r in flags], ['suspect', 'uncertain'])

    def test_complete_and_empty(self):
        self.assertEqual(self.summary()['reviewed'], 0)
        self.save([self.receipt([0, 1]), self.receipt([2], ['clean'])])
        self.assertTrue(self.summary()['complete'])

    def test_duplicate_partial_outofrange_and_invalid_choice_rejected(self):
        partial = self.receipt([0, 1]); del partial['response']['answers']['1']
        cases = [
            [self.receipt([0]), self.receipt([0])],
            [partial], [self.receipt([3])], [self.receipt([0], ['wrong'])],
        ]
        for receipts in cases:
            with self.subTest(receipts=receipts):
                self.save(receipts)
                with self.assertRaises(ValueError): self.summary()


if __name__ == '__main__':
    unittest.main()
