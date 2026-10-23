"""Model-free checks for exclusive native acceptance receipts."""
import ast
import importlib.util
import hashlib
import sys
from unittest.mock import AsyncMock, patch
import json
from pathlib import Path
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[1] / 'bolt_gateway_acceptance.py'
spec = importlib.util.spec_from_file_location('bolt_acceptance', PATH)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


class BoltAcceptance(unittest.TestCase):
    def test_exclusive_receipt_prevents_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'intent.json'
            a.save(p, {'submitted_once': True})
            self.assertEqual(json.loads(p.read_text()), {'submitted_once': True})
            with self.assertRaises(FileExistsError):
                a.save(p, {'submitted_once': False})
            self.assertEqual(json.loads(p.read_text()), {'submitted_once': True})

    def run_case(self, tmp, passed, output):
        fixtures = Path(tmp) / 'fixtures.json'
        raw = json.dumps({'maximum_native_requests': 12, 'no_replay_or_output_repair': True,
                          'cases': [{'id': str(i)} for i in range(12)]}).encode()
        if not fixtures.exists():
            fixtures.write_bytes(raw)
        argv = ['acceptance', '--fixtures', str(fixtures), '--fixtures-sha256', hashlib.sha256(raw).hexdigest(),
                '--gateway-sha256', 'a' * 64, '--case-id', '0', '--output', str(Path(tmp) / output)]
        with patch.object(a, 'LEDGER_ROOT', Path(tmp) / 'canonical-ledger'), patch.object(sys, 'argv', argv), \
                patch.object(a, 'execute', AsyncMock(return_value={'quality': {'passed': passed}})) as execute:
            if passed:
                a.main()
            else:
                with self.assertRaises(SystemExit) as error:
                    a.main()
                self.assertEqual(error.exception.code, 1)
            execute.assert_awaited_once()

    def test_different_output_cannot_replay_same_frozen_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_case(tmp, True, 'first')
            with self.assertRaises(FileExistsError):
                self.run_case(tmp, True, 'second')
            self.assertFalse((Path(tmp) / 'second').exists())

    def test_failed_quality_returns_nonzero_and_retains_result_and_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_case(tmp, False, 'failed')
            self.assertFalse(json.loads((Path(tmp) / 'failed/result.json').read_text())['quality']['passed'])
            with self.assertRaises(FileExistsError):
                self.run_case(tmp, True, 'do-not-retry')

    def test_capture_wraps_underlying_transport_before_strict_decoder(self):
        # A protocol rejection must not hide the once-only raw HTTP receipt.
        source = PATH.read_text()
        self.assertIn("transport = getattr(normalizer._opener, 'opener', normalizer._opener)", source)
        self.assertIn("patch.object(transport, 'open', side_effect=capture)", source)
        self.assertIn("save(root / 'http-result.json', item)", source)

    def test_generation_call_is_single_capture_not_retry(self):
        tree = ast.parse(PATH.read_text())
        execute = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'execute')
        capture = next(n for n in ast.walk(execute) if isinstance(n, ast.FunctionDef) and n.name == 'capture')
        dispatches = [n for n in ast.walk(capture) if isinstance(n, ast.Call)
                      and isinstance(n.func, ast.Name) and n.func.id == 'real_open']
        self.assertEqual(len(dispatches), 1)
        source = ast.unparse(capture)
        self.assertLess(source.index("'http-intent.json'"), source.index('real_open('))
        self.assertIn('Second native call prohibited', source)
        self.assertIn('Frozen accepted source drift', source)
        self.assertFalse(any(isinstance(n, (ast.For, ast.While)) for n in ast.walk(capture)))

    def test_no_private_audio_or_native_retry_import(self):
        source = PATH.read_text()
        self.assertIn("manifest['maximum_native_requests'] == 12", source)
        self.assertIn('collect, never replay', source)
        self.assertIn("'real_audio_or_owner_field': False", source)
        self.assertIn("observed_text == case['expected']", source)
        self.assertIn("'native_eos'", source)


if __name__ == '__main__':
    unittest.main()
