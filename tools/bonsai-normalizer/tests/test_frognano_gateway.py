"""Execute startup selection and the existing handler contract without hardware."""
import ast
import os
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent))
import test_gateway_seam_ast as contract_module
GATEWAY_SERVER_PATH = contract_module.GATEWAY_SERVER_PATH


class FrogNanoGateway(unittest.TestCase):
    def test_startup_precedence_and_invalid_config_never_selects_bonsai(self):
        tree = ast.parse(GATEWAY_SERVER_PATH.read_text())
        selected = next(n for n in tree.body if isinstance(n, ast.If)
                        and 'FROGNANO_NORMALIZER_CONFIG' in ast.unparse(n.test))
        frog, bonsai = ModuleType('gateway.frognano_normalizer'), ModuleType('gateway.bonsai_normalizer')
        frog.get_frognano_normalizer = Mock(return_value='frog')
        bonsai.get_bonsai_normalizer = Mock(return_value='bonsai')
        cases = [({'FROGNANO_NORMALIZER_CONFIG': 'new', 'BONSAI_NORMALIZER_CONFIG': 'old'}, 'frog'),
                 ({'BONSAI_NORMALIZER_CONFIG': 'old'}, 'bonsai'), ({}, None)]
        for env, expected in cases:
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True), patch.dict(sys.modules, {
                    'gateway.frognano_normalizer': frog, 'gateway.bonsai_normalizer': bonsai}):
                frog.get_frognano_normalizer.reset_mock()
                bonsai.get_bonsai_normalizer.reset_mock()
                ns = {'loqira_corrector': object(), 'STT_CORRECTOR': 'loqira',
                      'bonsai_normalizer': None, 'os': os}
                exec(compile(ast.Module(body=[selected], type_ignores=[]), str(GATEWAY_SERVER_PATH), 'exec'), ns)
                self.assertEqual(ns['bonsai_normalizer'], expected)
                self.assertLessEqual(frog.get_frognano_normalizer.call_count + bonsai.get_bonsai_normalizer.call_count, 1)
        frog.get_frognano_normalizer.return_value = None
        with patch.dict(os.environ, {'FROGNANO_NORMALIZER_CONFIG': 'invalid', 'BONSAI_NORMALIZER_CONFIG': 'old'}, clear=True), patch.dict(sys.modules, {
                'gateway.frognano_normalizer': frog, 'gateway.bonsai_normalizer': bonsai}):
            bonsai.get_bonsai_normalizer.reset_mock()
            exec(compile(ast.Module(body=[selected], type_ignores=[]), str(GATEWAY_SERVER_PATH), 'exec'), ns)
            self.assertIsNone(ns['bonsai_normalizer'])
            bonsai.get_bonsai_normalizer.assert_not_called()

    def test_frognano_env_only_smart_selection_and_exact_fallback(self):
        contract = contract_module.TestExecutedGatewaySeam()
        # Existing helper clears its environment, so map only its selected legacy key
        # to the new selector while exercising the real handler AST unchanged.
        original = os.environ.get
        def only_frog(key, default=None):
            if key == 'FROGNANO_NORMALIZER_CONFIG':
                return 'explicit-frog-config'
            if key == 'BONSAI_NORMALIZER_CONFIG':
                return None
            return original(key, default)
        with patch.object(os.environ, 'get', side_effect=only_frog):
            result = contract._execute(result=('wrong optional output', {'status': 'fallback'}))
            response, record, normalizer, events, _ = result
            self.assertEqual(response.content['text'], normalizer.normalize.call_args.args[0])
            self.assertTrue(any(name == 'bonsai' for name, _ in events))
            for mode in ('default', 'raw'):
                response, record, normalizer, events, _ = contract._execute(mode=mode)
                normalizer.normalize.assert_not_called()
                self.assertEqual(response.headers['X-Text-Editor-Status'], 'bypassed')


if __name__ == '__main__':
    unittest.main()
