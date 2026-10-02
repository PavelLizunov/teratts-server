"""Curated detection vocabulary, NOT executable commands or correction aliases."""
from difflib import SequenceMatcher
import re

TOPICS=("Разработка","Linux")
# Alternative suggestions deliberately retain semantic ambiguity.
GLOSSARY={
 "Разработка": [
  (("contributor",),r"контриб[ьюуи]*тор\w*|контреб[ьюуи]*тор\w*"),
  (("push","пуш"),r"(?:за|по|про)?пуш(?:ить|ил[аи]?|им|ите|ат|нуть|нул[аи]?|а|у|ем|ей|и|ов)?"),
  (("pull","pool","пул"),r"пулл?(?:а|у|ом|ы|ов|ам|ами|ах|ить|ил[аи]?|им|ите|нуть|нул[аи]?)?"),
  (("commit","коммит"),r"(?:за|по)?комм?ит\w*"),
  (("pull request",),r"пулл?\s+рек[вуе]*ест\w*|пулл?\s+риквест\w*"),
  (("merge","мердж"),r"(?:с|за)?мер[джг]+\w*|мерж\w*"),
  (("branch","ветка"),r"бран[чш]\w*"),
  (("repository","репозиторий"),r"реп[оа]зитор\w*|репо"),
  (("rebase",),r"(?:за)?реб[еэ]й[зс]\w*"),
  (("fork","форк"),r"форк\w*"),
  (("checkout",),r"чек[ао]ут\w*"),
  (("cherry-pick",),r"черри\s+пик\w*"),
  (("upstream",),r"апстрим\w*"),
  (("downstream",),r"даунстрим\w*"),
  (("remote",),r"ремоут\w*"),
  (("issue",),r"иш[ьюу]+\w*|иссь?ю\w*"),
  (("release","релиз"),r"релиз\w*"),
  (("build","сборка"),r"билд\w*"),
  (("debug","отладка"),r"деба[гк]\w*"),
  (("deploy","деплой"),r"депло[йи]\w*"),
  (("refactor","рефакторинг"),r"рефактор\w*"),
  (("dependency","зависимость"),r"депенденс\w*"),
  (("Git",),r"гит"),
  (("GitHub",),r"гитх[аэ]б\w*|гетхаб\w*"),
  (("GitLab",),r"гитлаб\w*"),
  (("plugin","плагин"),r"плагин\w*"),
  (("API",),r"апи|эйпиай"),
  (("SDK",),r"эсдика|эсдикей"),
  (("CI/CD",),r"си\s+ай\s+си\s+ди"),
  (("Rust",),r"раст"),
  (("Python",),r"пайтон|питон"),
  (("TypeScript",),r"тайпскрипт\w*|тайп\s+скрипт\w*"),
 ],
 "Linux": [
  (("Linux",),r"линукс\w*|лин[ау]кс\w*"),
  (("Arch",),r"арч|арча|арче"),
  (("Ubuntu",),r"убунту"),
  (("Debian",),r"дебиан\w*"),
  (("Fedora",),r"федора"),
  (("sudo",),r"судо"),
  (("systemd",),r"системд\w*|систем\s+ди"),
  (("systemctl",),r"систем\s+контрол\w*|системктл\w*"),
  (("journalctl",),r"журналктл\w*|джорнал\s+контрол\w*"),
  (("pacman",),r"пакман\w*"),
  (("yay",),r"яй"),
  (("apt",),r"апт"),
  (("dnf",),r"ди\s+эн\s+эф"),
  (("bash",),r"баш"),
  (("zsh",),r"зет\s+эс\s+эйч"),
  (("shell","шелл"),r"шелл?\w*"),
  (("terminal","терминал"),r"терминал\w*"),
  (("kernel","ядро"),r"кернел\w*|кернэл\w*"),
  (("daemon","демон"),r"демон\w*"),
  (("Docker",),r"докер\w*"),
  (("Podman",),r"подман\w*"),
  (("Wayland",),r"вейланд\w*|уэйленд\w*"),
  (("Hyprland",),r"хайпрл[аэ]нд\w*|хипрл[аэ]нд\w*"),
  (("GNOME",),r"гном\w*"),
  (("KDE",),r"ка\s+дэ\s+е"),
  (("pipewire",),r"пайпвай[ре]\w*"),
  (("PulseAudio",),r"пульс\s+аудио"),
  (("SSH",),r"эс\s+эс\s+эйч"),
  (("system service","сервис"),r"сервис\w*"),
  (("mount","монтирование"),r"маунт\w*"),
  (("filesystem","файловая система"),r"файл[ао]вая\s+система"),
  (("symlink","символическая ссылка"),r"симлинк\w*"),
  (("chmod",),r"чмод|чэмод|чмоде"),
  (("chown",),r"чоун"),
  (("grep",),r"греп\w*"),
  (("sed",),r"сед"),
  (("awk",),r"авк"),
  (("tmux",),r"тмакс|тмукс"),
  (("nix",),r"никс"),
  (("Flatpak",),r"флатпак\w*"),
  (("AppImage",),r"апп?им[еи]дж\w*"),
  (("udev",),r"юдев|удев"),
 ]}
TOKEN=re.compile(r"[^\W_]+",re.UNICODE)
PROTECTED=re.compile(r"```[\s\S]*?(?:```|\Z)|`[^`\n]*(?:`|\n|\Z)|https?://[^\s<>]+|\b[\w.-]+\.[a-z]{2,}(?:/\S*)?",re.I)


def suggestions(surface,topic):
    if topic not in GLOSSARY:return []
    text=surface.casefold().replace('ё','е')
    for choices,pattern in GLOSSARY[topic]:
        if re.fullmatch(pattern,text,re.I) or text in [term.casefold() for term in choices]:return list(choices)
    # Only long distinctive names can suggest approximate spellings, never short commands.
    close=[]
    if len(text)>=6:
        for choices,_ in GLOSSARY[topic]:
            for term in choices:
                if len(term)>=6 and SequenceMatcher(None,text,term.casefold()).ratio()>=0.84:
                    if term not in close:close.append(term)
    return close[:3]


def candidates(text,topic):
    if not isinstance(text,str) or topic not in GLOSSARY:return []
    text=text[:32768];protected=[m.span() for m in PROTECTED.finditer(text)];matches=[]
    for choices,pattern in GLOSSARY[topic]:
        exact='|'.join(re.escape(term) for term in choices)
        regex=re.compile(r"(?<!\w)(?:"+pattern+'|'+exact+r")(?!\w)",re.I)
        for m in regex.finditer(text):
            matches.append((m.start(),m.end(),list(choices),'Слово из технической темы; правильность и форму нужно проверить'))
    covered=[];result=[]
    # Prefer phrases over overlapping single words, e.g. pull request vs pull/pool.
    for start,end,choices,reason in sorted(matches,key=lambda row:(-(row[1]-row[0]),row[0])):
        if any(a<end and b>start for a,b in protected+covered):continue
        covered.append((start,end));result.append({'start':start,'end':end,'surface':text[start:end],
            'reason':reason+'; варианты: '+', '.join(choices),'label':'ambiguous'})
    for token in TOKEN.finditer(text):
        if any(a<token.end() and b>token.start() for a,b in protected+covered):continue
        choices=suggestions(token.group(),topic)
        if not choices:continue
        result.append({'start':token.start(),'end':token.end(),'surface':token.group(),
            'reason':'Возможное похожее техническое слово; не доказанная ошибка; варианты: '+', '.join(choices),'label':'suspected'})
    return sorted(result,key=lambda row:row['start'])[:100]
