"""Model-free frozen-rubric and canonical claim tests for rewrite checks."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bolt_rewrite_acceptance as a


class RewriteAcceptance(unittest.TestCase):
    def test_rubric_accepts_paraphrase_not_exact_text(self):
        case = {'required_patterns': {'request': r'проверь.*журнал'},
                'forbidden_pattern': r'блять', 'paragraphs': True}
        self.assertTrue(a.score('Проверь новый журнал.\n\nОтправь результат.', case)['rubric_passed'])
        self.assertFalse(a.score('Проверь журнал, блять.\n\nГотово.', case)['rubric_passed'])
        self.assertFalse(a.score('Проверь журнал. Отправь результат.', case)['rubric_passed'])
        self.assertFalse(a.score('Перезапусти сервер.\n\nГотово.', case)['rubric_passed'])
        self.assertTrue(a.score('Проверь журнал.\n\nДалее.', case)['manual_semantic_review_required'])

    def test_rewrite_claim_uses_shared_exclusive_ledger(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(a.receipts, 'LEDGER_ROOT', Path(temp) / 'ledger'):
            args = SimpleNamespace(fixtures_sha256=hashlib.sha256(b'frozen').hexdigest(),
                                   output=Path(temp) / 'one')
            path = a.receipts.claim_case(args, {'id': 'rewrite-fresh-case'})
            self.assertEqual(json.loads(path.read_text())['outcome'], 'consumed_or_unknown_do_not_replay')
            args.output = Path(temp) / 'two'
            with self.assertRaises(FileExistsError):
                a.receipts.claim_case(args, {'id': 'rewrite-fresh-case'})


if __name__ == '__main__':
    unittest.main()
