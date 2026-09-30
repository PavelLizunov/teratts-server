import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("runner", ROOT / "run_voice_teacher_pilot.py")
runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)


class Tests(unittest.TestCase):
    def test_normalized_agreement(self):
        result = runner.compare("Ёлка, привет!", "елка привет")
        self.assertEqual(result["category"], "normalized_agreement")
        self.assertFalse(result["human_gold"])
        self.assertFalse(result["training_approved"])

    def test_number_differences_not_hidden(self):
        self.assertNotEqual(runner.compare("код сорок два", "код 42")["category"], "normalized_agreement")

    def test_empty_and_disagreement(self):
        self.assertEqual(runner.compare("hello", "")["category"], "empty_teacher")
        self.assertEqual(runner.compare("одно", "совсем другое")["category"], "needs_review")

    def test_parse_json_and_fences(self):
        result = runner.parse_teacher('```json\n{"transcript":"Иван", "speech_present":true,"unclear":[]}\n```')
        self.assertEqual(result["transcript"], "Иван")
        for text in ['bad', '{"transcript":1,"speech_present":true}', '{"transcript":"x"}']:
            with self.assertRaises(ValueError): runner.parse_teacher(text)

    def test_durable_no_overwrite_private_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"result.json"
            runner.save_private(p,{"value":"exact"})
            self.assertEqual(p.stat().st_mode & 0o777,0o600)
            with self.assertRaises(FileExistsError):runner.save_private(p,{"value":"new"})

    def test_source_path_rejected_before_ssh(self):
        with self.assertRaises(ValueError):runner.fetch_sample({"filename":"../bad"})

if __name__ == "__main__":unittest.main(verbosity=2)
