import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from compare_voice_teacher_hints import paired_summary, terms_in


class Tests(unittest.TestCase):
    def test_term_boundaries(self):
        self.assertEqual(terms_in("Steam Deck и Bonsai.", ["Steam Deck", "Bonsai", "Omarchy"]), ["Steam Deck", "Bonsai"])
        self.assertEqual(terms_in("BonsaiX", ["Bonsai"]), [])

    def test_pairs_and_no_accuracy_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            blind, hinted = Path(tmp)/"blind", Path(tmp)/"hinted"
            blind.mkdir(); hinted.mkdir()
            data={"sample_id":"id","audio_sha256":"hash","status":"completed",
                  "teacher":{"transcript":"стимдек"},"comparison":{"category":"needs_review"}}
            (blind/"id.json").write_text(json.dumps(data))
            updated={**data,"teacher":{"transcript":"Steam Deck"},"vocabulary_hints":["Steam Deck"],
                     "teacher_saw_primary_text":False,"teacher_saw_blind_transcript":False}
            (hinted/"id.json").write_text(json.dumps(updated))
            summary=paired_summary(blind,hinted)
            self.assertEqual(summary["paired_records"],1)
            self.assertEqual(summary["vocabulary_added"],{"Steam Deck":1})
            self.assertFalse(summary["accuracy_measured"])
            updated["audio_sha256"]="different"
            (hinted/"id.json").write_text(json.dumps(updated))
            with self.assertRaises(ValueError):paired_summary(blind,hinted)

if __name__=="__main__":unittest.main(verbosity=2)
