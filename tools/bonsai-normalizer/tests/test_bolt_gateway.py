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

    def test_bolt_smart_only_optouts_and_exact_accepted_fallback(self):
        helper = contract.TestExecutedGatewaySeam()
        # Even a stale client advertising default editing cannot expand gateway routing.
        bolt = {'editor_selector': 'BOLT_NORMALIZER_CONFIG', 'edit_default_mode': True}
        for status in ('fallback', 'unchanged', 'bypassed', 'unexpected'):
            response, record, normalizer, events, _ = helper._execute(
                **bolt, mode='smart', result=('must not escape', {'status': status}),
                loqira_text='Ну, смотри, открой гитхап.\r\n\tНе меняй порт 4628.  ')
            accepted = normalizer.normalize.call_args.args[0]
            self.assertEqual(response.content['text'].encode(), accepted.encode())
            self.assertEqual(record['accepted_stt_text'], accepted)
            self.assertNotEqual(record['raw_text'], accepted)
        for mode in ('default', 'smart', 'raw'):
            for smart in (False, True):
                for formatting in (False, True):
                    with self.subTest(mode=mode, smart=smart, formatting=formatting):
                        response, record, normalizer, events, _ = helper._execute(
                            **bolt, mode=mode, smart=smart, formatting=formatting,
                            result=('Accepted edit.', {'status': 'applied'}))
                        raw = mode == 'raw' or not formatting
                        effective = 'raw' if raw else 'smart' if smart else mode
                        edited = effective == 'smart'
                        self.assertEqual(response.headers['X-Mode'], effective)
                        self.assertEqual(response.headers['X-Text-Editor-Status'],
                                         'applied' if edited else 'bypassed')
                        self.assertEqual('loqira' in [event[0] for event in events], not raw)
                        if edited:
                            normalizer.normalize.assert_called_once_with(record['accepted_stt_text'])
                            self.assertEqual(response.content['text'], 'Accepted edit.')
                        else:
                            normalizer.normalize.assert_not_called()
                            self.assertEqual(response.content['text'], record['accepted_stt_text'])

    def test_bolt_default_preserves_changed_loqira_bytes_without_editor(self):
        helper = contract.TestExecutedGatewaySeam()
        expected = 'Исправленный текст.\r\n\tНе меняй порт 4628.  '
        response, record, normalizer, events, _ = helper._execute(
            mode='default', editor_selector='BOLT_NORMALIZER_CONFIG', edit_default_mode=True,
            asr_text='Сырой текст распознавания.', loqira_text=expected,
            dictionary=False, cleanup=False, error=AssertionError('Default must not call Bolt'))
        normalizer.normalize.assert_not_called()
        self.assertIn('loqira', [event[0] for event in events])
        self.assertNotEqual(record['raw_text'], expected)
        self.assertEqual(response.content['text'].encode(), expected.encode())
        self.assertEqual(record['accepted_stt_text'].encode(), expected.encode())
        self.assertEqual(response.headers['X-Text-Editor-Status'], 'bypassed')

    def test_historical_editors_remain_smart_only(self):
        helper = contract.TestExecutedGatewaySeam()
        for selector in ('FROGNANO_NORMALIZER_CONFIG', 'BONSAI_NORMALIZER_CONFIG'):
            response, _, normalizer, _, _ = helper._execute(
                mode='default', editor_selector=selector, edit_default_mode=True)
            normalizer.normalize.assert_not_called()
            self.assertEqual(response.headers['X-Text-Editor-Status'], 'bypassed')

    def test_service_prompt_matches_client_without_model_imports(self):
        tools = Path(__file__).resolve().parents[2]
        def constant(path, name):
            tree = ast.parse(path.read_text())
            return next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
        self.assertEqual(constant(tools / 'bolt-stt/bolt_service.py', 'SYSTEM_PROMPT'),
                         constant(tools / 'bonsai-normalizer/bolt_normalizer.py', 'BOLT_SYSTEM_PROMPT'))


if __name__ == '__main__':
    unittest.main()
