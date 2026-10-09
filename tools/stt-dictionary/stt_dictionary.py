"""Explicit approved spellings and optional leading filler cleanup, no inference."""
import json
import hashlib
from pathlib import Path
import re

RULE_ID = "personal-spelling-v5"
BOUND_LEFT=r"(?<![\w/@.\\+\-])"
BOUND_RIGHT=r"(?![\w/@\\+\-]|\.[\w])"
GITHUB=re.compile(BOUND_LEFT+r"(?:github|git[ \t]+hub|гитхап|гитхаба?|гетхаб|гитха|гетха|гит[ \t]+хаб)"+BOUND_RIGHT,re.I)
OMARCHY=re.compile(BOUND_LEFT+r"(?:omarchy|омарчи|умрчи)"+BOUND_RIGHT,re.I)
PLUGIN=re.compile(BOUND_LEFT+r"(?:плагин(?:а|у|ом|е|ы|ов|ам|ами|ах)?|plugins?)"+BOUND_RIGHT,re.I)
CHATGPT_BASE=r"(?:chat[ \t]*gpt|чат[ \t-]*(?:gpt|гпт|джи[ \t-]*пи[ \t-]*ти|джипити|джибити|гпити))"
CHATGPT=re.compile(BOUND_LEFT+CHATGPT_BASE+r"(?:[ \t]+(?:pro|про))?"+BOUND_RIGHT,re.I)
PROTECTED = re.compile(
    r"```[\s\S]*?(?:```|\Z)|`[^`\n]*(?:`|\n|\Z)"
    r"|\[[^\]\n]*\]\([^\)\n]*\)"
    r"|https?://[^\s<>]+|[\w.+-]+@[\w.-]+"
    r"|(?:[A-Za-z]:[\\/]|(?<!\w)[./~])[\w./\\+@:-]+"
    r"|\b[\w-]+(?:[./\\][\w.-]+)+", re.IGNORECASE)


def replace_exact(text,pattern,canonical,rule):
    protected=[m.span() for m in PROTECTED.finditer(text)];changes=[]
    def replace(match):
        if match.group()==canonical or any(a<match.end() and b>match.start() for a,b in protected):return match.group()
        changes.append({"rule":rule,"start":match.start(),"end":match.end(),"before":match.group(),"after":canonical,
                        "offset_basis":"text_before_this_rule"})
        return canonical
    return pattern.sub(replace,text),changes


def normalize_github(text):
    return replace_exact(text,GITHUB,"GitHub","github-spelling-v2")


def normalize_omarchy(text):
    return replace_exact(text,OMARCHY,"Omarchy","omarchy-spelling-v1")


def normalize_plugin(text):
    return replace_exact(text,PLUGIN,"plugin","plugin-canonical-v1")


def normalize_chatgpt(text):
    protected=[m.span() for m in PROTECTED.finditer(text)];changes=[]
    def replace(match):
        if any(a<match.end() and b>match.start() for a,b in protected):return match.group()
        canonical='ChatGPT Pro' if re.search(r'[ \t]+(?:pro|про)$',match.group(),re.I) else 'ChatGPT'
        if match.group()==canonical:return canonical
        changes.append({'rule':'chatgpt-spelling-v1','start':match.start(),'end':match.end(),
            'before':match.group(),'after':canonical,'offset_basis':'text_before_this_rule'})
        return canonical
    return CHATGPT.sub(replace,text),changes


CANONICAL_RULES={"GitHub":"github","Omarchy":"omarchy","plugin":"plugin","ChatGPT":"chatgpt","ChatGPT Pro":"chatgpt"}

def normalize_aliases(text,config):
    """Exact user-approved aliases; literal strings only, never fuzzy patterns."""
    aliases=config.get("aliases",{})
    if not isinstance(aliases,dict) or len(aliases)>256:return text,[]
    replacements={}
    for surface,canonical in aliases.items():
        if (not isinstance(surface,str) or not 1<=len(surface)<=80 or
            not isinstance(canonical,str) or canonical not in CANONICAL_RULES or
            config.get(CANONICAL_RULES[canonical]) is not True or
            not re.fullmatch(r"[\w \t-]+",surface)):
            continue
        replacements[surface.casefold()]=canonical
    if not replacements:return text,[]
    pattern=re.compile(BOUND_LEFT+r"(?:"+"|".join(re.escape(s) for s in sorted(replacements,key=len,reverse=True))+r")"+BOUND_RIGHT,re.I)
    protected=[m.span() for m in PROTECTED.finditer(text)];changes=[]
    def replace(match):
        canonical=replacements[match.group().casefold()]
        if match.group()==canonical or any(a<match.end() and b>match.start() for a,b in protected):return match.group()
        changes.append({"rule":"approved-exact-alias-v1","start":match.start(),"end":match.end(),"before":match.group(),"after":canonical,"offset_basis":"text_before_this_rule"})
        return canonical
    return pattern.sub(replace,text),changes


def apply_dictionary(text,config_path,requested=True):
    if not requested:return text,{"status":"request_disabled","rule":RULE_ID,"changes":[]}
    try:
        path=Path(config_path)
        if path.stat().st_size>4096:raise ValueError("Oversized config")
        data=path.read_bytes();config=json.loads(data)
        if not isinstance(config,dict):raise ValueError("Invalid config")
    except (OSError,ValueError,TypeError):return text,{"status":"config_unavailable","rule":RULE_ID,"changes":[]}
    active=[];text,changes=normalize_aliases(text,config)
    for name,normalizer in [("github",normalize_github),("omarchy",normalize_omarchy),("plugin",normalize_plugin),("chatgpt",normalize_chatgpt)]:
        if config.get(name) is True:
            active.append(name);text,updates=normalizer(text);changes.extend(updates)
    return text,{"status":"applied" if changes else "unchanged" if active else "config_disabled",
                 "rule":RULE_ID,"active_rules":active,"changes":changes,"config_sha256":hashlib.sha256(data).hexdigest()}


def clean_opening(text,requested=False):
    """Opt-in cleanup, punctuation-delimited only. Maria is NEVER touched."""
    if not requested:return text,{"status":"request_disabled","changes":[]}
    original=text;changes=[]
    for _ in range(2):
        match=re.match(r"^\s*(?:ну|смотри)\s*[,：:]\s*",text,re.I)
        if not match:break
        rest=text[match.end():]
        if len(re.findall(r"\w+",rest))<2:break
        changes.append({"rule":"opening-filler-v1","before":match.group(),"after":"",
                        "start":0,"end":match.end(),"offset_basis":"text_before_this_rule"})
        text=rest
    return text,{"status":"applied" if changes else "unchanged","changes":changes,
                 "pre_cleanup_text":original}
