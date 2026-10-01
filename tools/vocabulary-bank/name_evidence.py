"""Broad named-term candidates for human review, never replacement aliases."""
from difflib import SequenceMatcher
import hashlib
import re

VERSION = "github-evidence-v1"
MAX_TEXT = 32768
TOKENS = re.compile(r"[^\W_]+", re.UNICODE)
PROTECTED = re.compile(r"```[\s\S]*?(?:```|\Z)|`[^`\n]*(?:`|\n|\Z)|https?://[^\s<>]+|\b[\w.-]+\.[a-z]{2,}(?:/\S*)?", re.I)


def fold(word):
    word=word.casefold().replace("ё","е")
    table=str.maketrans({"г":"g","и":"i","е":"e","т":"t","х":"h","а":"a","б":"b","п":"p","у":"u","э":"e","в":"v","й":"i"})
    return word.translate(table)


def candidates(text, canonical="GitHub"):
    if canonical!="GitHub" or not isinstance(text,str):return []
    text=text[:MAX_TEXT];tokens=list(TOKENS.finditer(text));protected=[m.span() for m in PROTECTED.finditer(text)]
    result=[];used=set()
    for index,token in enumerate(tokens):
        start,end=token.span();word=fold(token.group());reason=None;label="suspected"
        if index+1<len(tokens):
            next_token=tokens[index+1];pair=(word,fold(next_token.group()))
            between=text[end:next_token.start()]
            if pair in [("git","hub"),("git","hab"),("git","hap"),("hub","git"),("hab","git")] and between.strip()=="":
                end=next_token.end();reason="Раздельное или переставленное git + hub";label="ambiguous" if pair[0] in ["hub","hab"] else "likely"
                used.add(index+1)
        if index in used:continue
        if reason is None:
            if word in ["github","githab","githap","gethab","gethap","githa","getha"]:
                reason="Название или близкий вариант произношения";label="likely"
            elif word in ["git","gitab","gitlab","gith","gethub","githup"]:
                reason="Неоднозначный вариант: возможны Git, GitLab или GitHub";label="ambiguous"
            elif 4<=len(word)<=9 and word.startswith(("git","get")) and SequenceMatcher(None,word,"github").ratio()>=0.60:
                reason="Похожее написание — требуется прослушивание";label="suspected"
        if reason and not any(a<end and b>start for a,b in protected):
            result.append({"start":start,"end":end,"surface":text[start:end],"reason":reason,"label":label})
        if len(result)>=100:break
    return result


def ensure_schema(connection):
    connection.executescript('''
      CREATE TABLE IF NOT EXISTS name_scans(source TEXT PRIMARY KEY,version TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS name_documents(source TEXT NOT NULL,stage TEXT NOT NULL,text TEXT NOT NULL,sample_ref TEXT,text_hash TEXT NOT NULL,PRIMARY KEY(source,stage));
      CREATE TABLE IF NOT EXISTS name_mentions(id INTEGER PRIMARY KEY,source TEXT NOT NULL,stage TEXT NOT NULL,canonical TEXT NOT NULL,start INTEGER NOT NULL,end INTEGER NOT NULL,surface TEXT NOT NULL,reason TEXT NOT NULL,label TEXT NOT NULL,UNIQUE(source,stage,canonical,start,end));
      CREATE INDEX IF NOT EXISTS name_mentions_term ON name_mentions(canonical,id);
    ''')


def stages(metadata):
    if metadata.get("kind")=="stt":
        yield "stt_raw",metadata.get("raw_text",""),metadata.get("sample_id")
    elif metadata.get("kind")=="vocabulary_teacher_record":
        # Preserve teacher origin; primary already indexed from original STT WAV.
        yield "teacher_hinted" if metadata.get("vocabulary_hints") else "teacher_blind",metadata.get("teacher_text",""),metadata.get("original_sample_id")


def import_evidence(connection,source,metadata):
    if connection.execute("SELECT 1 FROM name_scans WHERE source=? AND version=?",(source,VERSION)).fetchone():return False
    rid=metadata.get("client_context",{}).get("headers",{}).get("x-request-id","")
    if not (isinstance(rid,str) and rid.startswith("synthetic")):
        for stage,text,sample in stages(metadata):
            if not isinstance(text,str):continue
            text=text[:MAX_TEXT];mentions=candidates(text)
            if not mentions:continue
            digest=hashlib.sha256(text.encode()).hexdigest()
            connection.execute("INSERT OR IGNORE INTO name_documents VALUES(?,?,?,?,?)",(source,stage,text,sample,digest))
            for m in mentions:
                connection.execute("INSERT OR IGNORE INTO name_mentions(source,stage,canonical,start,end,surface,reason,label) VALUES(?,?,?,?,?,?,?,?)",
                    (source,stage,"GitHub",m["start"],m["end"],m["surface"],m["reason"],m["label"]))
    connection.execute("INSERT INTO name_scans VALUES(?,?) ON CONFLICT(source) DO UPDATE SET version=excluded.version",(source,VERSION))
    return True
