import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stt_dictionary import normalize_github,apply_dictionary

class Tests(unittest.TestCase):
    def test_explicit_variants_and_repetitions(self):
        text="Гитхап, Гитхаб, Гит Хаб. На github и на GITHUB, GitHub."
        result,changes=normalize_github(text)
        self.assertEqual(result,"GitHub, GitHub, GitHub. На GitHub и на GitHub, GitHub.")
        self.assertEqual(len(changes),5)
        for change in changes:self.assertEqual(text[change['start']:change['end']],change['before'])
    def test_unrelated_words_and_affixes(self):
        for text in ["Гит работает, хаб выключен", "Гитхабовский", "GitHubAction", "mygithub", "Бонсай и Omarchy", "Гитхабу", "на гитхабе"]:
            self.assertEqual(normalize_github(text),(text,[]))
    def test_url_code_path_email_unchanged(self):
        for text in ["https://github.com/User/Repo", "github.com/user", "github/repo", "./github", "/tmp/Гитхаб", "C:\\github\\repo", "user@github.com", "`github`", "```\ngithub\n```", "[GitHub](https://github.com)", "foo.github", "github-коммит", "github_api"]:
            self.assertEqual(normalize_github(text),(text,[]))
    def test_boundaries_quotes_and_sentence(self):
        self.assertEqual(normalize_github('«гитхап». GitHub!')[0],'«GitHub». GitHub!')
        self.assertEqual(normalize_github('github.')[0],'GitHub.')
    def test_config_disabled_request_optout_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"rule.json";p.write_text(json.dumps({"github":True}))
            text,meta=apply_dictionary("Гитхап",p)
            self.assertEqual(text,"GitHub");self.assertEqual(meta['status'],'applied')
            self.assertEqual(apply_dictionary("Гитхап",p,False)[0],"Гитхап")
            p.write_text('{"github": false}')
            self.assertEqual(apply_dictionary("Гитхап",p)[1]['status'],'config_disabled')
            p.write_text('bad')
            self.assertEqual(apply_dictionary("Гитхап",p)[1]['status'],'config_unavailable')
            p.unlink()
            self.assertEqual(apply_dictionary("Гитхап",p)[0],"Гитхап")
    def test_empty_input(self):self.assertEqual(normalize_github(""),("",[]))
if __name__=="__main__":unittest.main(verbosity=2)
