import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('pilot',ROOT/'run_nemotron_pilot.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class Tests(unittest.TestCase):
    def test_fixed_small_manifest(self):
        m.validate_manifest({'samples':[{'file':'1.wav','duration_s':8}], 'hints':['Omarchy'],'boost':2})
        for d in [
            {'samples':[{'file':'1.wav','duration_s':91}], 'hints':[],'boost':2},
            {'samples':[{'file':'../a.wav','duration_s':1}], 'hints':[],'boost':2},
            {'samples':[{'file':'1.wav','duration_s':1}], 'hints':['a']*7,'boost':2},
            {'samples':[{'file':'1.wav','duration_s':1}], 'hints':[],'boost':20},
            {'samples':[{'file':'1.wav','duration_s':1}]*9,'hints':[],'boost':2}]:
            with self.assertRaises(ValueError):m.validate_manifest(d)
    def test_nonproduction_source_contract(self):
        source=(ROOT/'run_nemotron_pilot.py').read_text()
        self.assertIn("'--device','cpu'",source)
        self.assertIn("'--speech-context-boost','2'",source)
        self.assertNotIn('systemctl restart',source)
        self.assertNotIn('/v1/audio/transcriptions',source)
class SummaryTests(unittest.TestCase):
    def test_disabled_boost_cannot_count_as_context_test(self):
        import tempfile,json
        spec=importlib.util.spec_from_file_location('summary',ROOT/'summarize_nemotron_pilot.py')
        summary=importlib.util.module_from_spec(spec);spec.loader.exec_module(summary)
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            for mode in ['plain','hinted']:
                data={'sample_id':'s','mode':mode,'category':'test','result':{'text':'слово'},'wall_seconds_cold_cli':1,
                      'diagnostic_tail':'boosting disabled' if mode=='hinted' else ''}
                (folder/(mode+'.record.json')).write_text(json.dumps(data))
            result=summary.summarize(folder)
            self.assertEqual(result['context_disabled_pairs'],1)
            self.assertEqual(result['text_changed_pairs'],0)
            self.assertFalse(result['accuracy_measured'])
            self.assertFalse(result['production_vulkan_speed_compared'])
if __name__=='__main__':unittest.main(verbosity=2)
