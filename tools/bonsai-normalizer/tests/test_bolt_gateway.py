"""Execute Bolt startup and smart-only gateway seam without native inference."""
import ast
import os
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent))
import test_gateway_seam_ast as contract


class GatewayHealthIdentity(unittest.TestCase):
    def test_health_exposes_actual_editor_without_calling_it(self):
        tree = ast.parse(contract.GATEWAY_SERVER_PATH.read_text())
        health = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'health')
        health.decorator_list = []
        ns = {'STT_BACKEND': 'stub', 'STT_IDENTITY': {}, 'SAGE_READY': False,
              'CORRECTOR_IDENTITY': {}, 'CORRECTOR_POLICY': 'stub', 'loqira_corrector': None,
              'bonsai_normalizer': Mock(model='actual-bolt', revision='exact-revision', enabled=True)}
        exec(compile(ast.Module(body=[health], type_ignores=[]), 'health', 'exec'), ns)
        self.assertEqual(ns['health']()['text_editor'],
                         {'status': 'configured', 'model': 'actual-bolt', 'revision': 'exact-revision'})
        ns['bonsai_normalizer'].normalize.assert_not_called()
        ns['bonsai_normalizer'] = None
        self.assertEqual(ns['health']()['text_editor'],
                         {'status': 'bypassed', 'model': None, 'revision': None})


class BoltGateway(unittest.TestCase):
    def test_priority_and_fail_closed(self):
        tree = ast.parse(contract.GATEWAY_SERVER_PATH.read_text())
        selected = next(n for n in tree.body if isinstance(n, ast.If)
                        and 'BOLT_NORMALIZER_CONFIG' in ast.unparse(n.test))
        modules = {}
        factories = {}
        for name in ('bolt', 'frognano', 'bonsai'):
            module = ModuleType('gateway.' + name + '_normalizer')
            factory = Mock(return_value=name)
            setattr(module, 'get_' + name + '_normalizer', factory)
            modules[module.__name__] = module
            factories[name] = factory
        cases = [({'BOLT_NORMALIZER_CONFIG': 'new', 'FROGNANO_NORMALIZER_CONFIG': 'old',
                   'BONSAI_NORMALIZER_CONFIG': 'old'}, 'bolt'),
                 ({'BOLT_NORMALIZER_CONFIG': '', 'FROGNANO_NORMALIZER_CONFIG': 'old',
                   'BONSAI_NORMALIZER_CONFIG': 'old'}, 'bolt'),
                 ({'FROGNANO_NORMALIZER_CONFIG': 'old'}, 'frognano'),
                 ({'BONSAI_NORMALIZER_CONFIG': 'old'}, 'bonsai'), ({}, None)]
        for env, expected in cases:
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True), patch.dict(sys.modules, modules):
                for factory in factories.values():
                    factory.reset_mock()
                ns = {'loqira_corrector': object(), 'STT_CORRECTOR': 'loqira',
                      'bonsai_normalizer': None, 'os': os}
                exec(compile(ast.Module(body=[selected], type_ignores=[]), str(contract.GATEWAY_SERVER_PATH), 'exec'), ns)
                self.assertEqual(ns['bonsai_normalizer'], expected)
                self.assertLessEqual(sum(f.call_count for f in factories.values()), 1)
        for outcome in (None, RuntimeError('invalid config')):
            factories['bolt'].return_value = outcome
            factories['bolt'].side_effect = outcome if isinstance(outcome, Exception) else None
            with patch.dict(os.environ, {'BOLT_NORMALIZER_CONFIG': 'bad', 'FROGNANO_NORMALIZER_CONFIG': 'old',
                                        'BONSAI_NORMALIZER_CONFIG': 'old'}, clear=True), patch.dict(sys.modules, modules):
                factories['frognano'].reset_mock()
                factories['bonsai'].reset_mock()
                ns['bonsai_normalizer'] = None
                exec(compile(ast.Module(body=[selected], type_ignores=[]), str(contract.GATEWAY_SERVER_PATH), 'exec'), ns)
                self.assertIsNone(ns['bonsai_normalizer'])
                factories['frognano'].assert_not_called()
                factories['bonsai'].assert_not_called()

    def test_only_bolt_env_smart_selection_and_exact_accepted_fallback(self):
        helper = contract.TestExecutedGatewaySeam()
        original = os.environ.get
        def only_bolt(key, default=None):
            if key == 'BOLT_NORMALIZER_CONFIG':
                return 'explicit-bolt'
            if key in ('FROGNANO_NORMALIZER_CONFIG', 'BONSAI_NORMALIZER_CONFIG'):
                return None
            return original(key, default)
        with patch.object(os.environ, 'get', side_effect=only_bolt):
            for status in ('fallback', 'unchanged', 'bypassed', 'unexpected'):
                response, record, normalizer, events, _ = helper._execute(
                    result=('must not escape', {'status': status}),
                    loqira_text='Ну, смотри, открой гитхап.\r\n\tНе меняй порт 4628.  ')
                accepted = normalizer.normalize.call_args.args[0]
                self.assertEqual(response.content['text'].encode(), accepted.encode())
                self.assertEqual(record['accepted_stt_text'], accepted)
                self.assertNotEqual(record['raw_text'], accepted)
            for options in ({'mode': 'default'}, {'mode': 'raw'}, {'mode': 'smart', 'formatting': False}):
                response, record, normalizer, events, _ = helper._execute(**options)
                normalizer.normalize.assert_not_called()
                self.assertEqual(response.headers['X-Text-Editor-Status'], 'bypassed')
            response, record, normalizer, events, _ = helper._execute(result=('Accepted edit.', {'status': 'applied'}))
            normalizer.normalize.assert_called_once()
            self.assertEqual(response.content['text'], 'Accepted edit.')


if __name__ == '__main__':
    unittest.main()
