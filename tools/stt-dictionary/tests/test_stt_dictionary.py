import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stt_dictionary import normalize_github,normalize_omarchy,normalize_plugin,normalize_chatgpt,apply_dictionary,clean_opening

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
    def test_confirmed_github_additions_and_ambiguity(self):
        self.assertEqual(normalize_github("гитха гетха Гетхаб Гитхаба git hub")[0],"GitHub GitHub GitHub GitHub GitHub")
        for text in ["git gitab hub git GitLab", "git hub/repo", "`гетха`"]:
            self.assertEqual(normalize_github(text),(text,[]))
    def test_omarchy_and_unrelated_merch(self):
        self.assertEqual(normalize_omarchy("Плагины для Омарчи и Умрчи, omarchy.")[0],"Плагины для Omarchy и Omarchy, Omarchy.")
        for text in ["Я купил мерч", "Мария пишет плагины", "https://omarchy.org", "./omarchy", "omarchy_plugin"]:
            self.assertEqual(normalize_omarchy(text),(text,[]))
    def test_cleanup_opt_in_and_semantics(self):
        text="Ну, смотри, плагины для Omarchy работают."
        self.assertEqual(clean_opening(text)[0],text)
        self.assertEqual(clean_opening(text,True)[0],"плагины для Omarchy работают.")
        for text in ["Мария, посмотри плагины", "Смотри фильм", "Ну и что?", "Смотри, фильм", "Смотри", "`Ну, слово`", "Там, ну, плагины"]:
            self.assertEqual(clean_opening(text,True)[0],text)
    def test_rules_independent_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"rule.json";p.write_text('{"github":false,"omarchy":true}')
            self.assertEqual(apply_dictionary("гитха Омарчи",p)[0],"гитха Omarchy")
    def test_plugin_all_inflections_intentionally_collapsed(self):
        forms='плагин плагина плагину плагином плагине плагины плагинов плагинам плагинами плагинах Plugin plugins'
        text,changes=normalize_plugin(forms)
        self.assertEqual(text,' '.join(['plugin']*12));self.assertEqual(len(changes),12)
        for original in ['плагинный','плагинок','плаги','./плагин','/tmp/plugins','https://x.test/plugin','plugin_name','`плагины`','plugins/foo']:
            self.assertEqual(normalize_plugin(original),(original,[]))
    def test_plugin_config_and_optout(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'r.json';p.write_text('{"plugin":true}')
            self.assertEqual(apply_dictionary('два плагина и GitHub',p)[0],'два plugin и GitHub')
            self.assertEqual(apply_dictionary('плагины',p,False)[0],'плагины')
    def test_chatgpt_exact_pro_and_no_suffix_loss(self):
        text='chat gpt, чат джибити про, чат джи пи ти, chatgpt pro и чат GPT про'
        self.assertEqual(normalize_chatgpt(text)[0],'ChatGPT, ChatGPT Pro, ChatGPT, ChatGPT Pro и ChatGPT Pro')
        self.assertEqual(normalize_chatgpt('chat gpt plus')[0],'ChatGPT plus')
        for text in ['GPT Pro', 'джибити', 'https://chatgpt.com', '`chat gpt pro`','chatgpt_pro','chat gpt/repo','chatgpt.pro']:
            self.assertEqual(normalize_chatgpt(text),(text,[]))
    def test_chatgpt_independent_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'r.json';p.write_text('{"chatgpt":true,"plugin":true}')
            self.assertEqual(apply_dictionary('чат джибити про и плагины',p)[0],'ChatGPT Pro и plugin')
            self.assertEqual(apply_dictionary('чат джибити про',p,False)[0],'чат джибити про')
    def test_approved_config_aliases_exact_complaints(self):
        p=ROOT/'deploy/stt-dictionary.json'
        text='чат-джипти, чат-джипти, дпти чат, чат-джиптипро. Чар Джи Пяти про. Амарче, Амарчи, Марчи, Амарчик. plug in.'
        out,meta=apply_dictionary(text,p)
        self.assertEqual(out,'ChatGPT, ChatGPT, ChatGPT, ChatGPT Pro. ChatGPT Pro. Omarchy, Omarchy, Omarchy, Omarchy. plugin.')
        self.assertEqual(meta['rule'],'personal-spelling-v5')
        self.assertEqual(meta['status'],'applied')
        self.assertEqual(apply_dictionary(out,p)[0],out)
        self.assertEqual(apply_dictionary(text,p,False)[0],text)
    def test_alias_protected_false_positive_and_switches(self):
        p=ROOT/'deploy/stt-dictionary.json'
        for text in ['Мария купила мерч и марки','GPT Pro','джипти','Амарчинский','`чат-джипти`','/tmp/амарчи','https://test/чат-джипти','амарчи_api','[чат-джипти](https://example.org)','chat-джипти-file']:
            self.assertEqual(apply_dictionary(text,p)[0],text)
        with tempfile.TemporaryDirectory() as tmp:
            config=json.loads(p.read_text());config['chatgpt']=False
            q=Path(tmp)/'r.json';q.write_text(json.dumps(config,ensure_ascii=False))
            self.assertEqual(apply_dictionary('чат-джипти Амарчи',q)[0],'чат-джипти Omarchy')
            config['aliases']['новое имя']='Omarchy';q.write_text(json.dumps(config,ensure_ascii=False))
            self.assertEqual(apply_dictionary('новое имя',q)[0],'Omarchy')
    def test_empty_input(self):self.assertEqual(normalize_github(""),("",[]))
if __name__=="__main__":unittest.main(verbosity=2)
