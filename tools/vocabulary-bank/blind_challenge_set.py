"""Deterministic hard-case selection, not random quality estimate or model truth."""
from difflib import SequenceMatcher
import hashlib
import json
import re

VERSION='long-content-v1'
TECH=re.compile(r'github|gitlab|г[ие]тх|omarchy|[аоу]марч|plugin|плаг|чат|gpt|контриб|contributor|репозит|\b(?:git|pull|push|sudo|linux|api|cpu|gpu|docker|systemd)\b',re.I)
NEGATIONS={'не','нет','нельзя','без','not','no','never'}


def words(text):return re.findall(r'\w+',text.casefold().replace('ё','е'))


def features(primary,candidate,duration):
    a,b=words(primary),words(candidate)
    if not 5<=duration<=40 or min(len(a),len(b))<12 or a==b:return None
    matcher=SequenceMatcher(None,a,b,autojunk=False);ratio=matcher.ratio()
    if ratio>=0.95:return None
    blocks=[(a[i:j],b[x:y]) for op,i,j,x,y in matcher.get_opcodes() if op!='equal']
    changed=sum(max(len(left),len(right)) for left,right in blocks)
    if changed<3:return None
    changed_a=[w for left,_ in blocks for w in left];changed_b=[w for _,right in blocks for w in right]
    tech=bool(TECH.search(' '.join(changed_a+changed_b)))
    numbers=lambda tokens:[w for w in tokens if any(ch.isdigit() for ch in w)]
    numeric=numbers(a)!=numbers(b)
    negation=[w for w in a if w in NEGATIONS]!=[w for w in b if w in NEGATIONS]
    reasons=[]
    if tech:reasons.append('Различаются технические слова')
    if numeric:reasons.append('Различаются числа или версии')
    if negation:reasons.append('Различаются отрицания — проверь смысл')
    if not reasons:reasons.append('Несколько содержательных различий в длинной фразе')
    score=4*tech+3*numeric+3*negation+min(changed,15)/5+min(duration,20)/20
    return {'ratio':round(ratio,4),'changed_words':changed,'technical':tech,'numbers':numeric,'negation':negation,
            'reasons':reasons,'score':round(score,4),
            'bucket':'technical' if tech else 'number_negation' if numeric or negation else 'lexical'}


def select(c,size=30):
    if not 2<=size<=100 or size%2:raise ValueError('Even bounded selection required')
    feedback=bool(c.execute("SELECT 1 FROM sqlite_master WHERE name='feedback'").fetchone())
    condition="WHERE NOT EXISTS(SELECT 1 FROM feedback f WHERE f.target_kind='blind_comparison' AND f.target_key=b.token)" if feedback else ''
    candidates=[]
    for row in c.execute('SELECT b.token,b.option1_primary,m.audio_sha,m.primary_text,m.candidate_text,m.duration FROM blind_assignments b JOIN model_comparisons m ON m.audio_sha=b.audio_sha '+condition):
        token,orientation,sha,primary,candidate,duration=row
        f=features(primary,candidate,duration)
        if f:candidates.append({'token':token,'orientation':orientation,'sha':sha,'primary':primary,'candidate':candidate,'duration':duration,**f})
    candidates.sort(key=lambda r:(-r['score'],r['sha']))
    selected=[];counts={0:0,1:0};seen_text=set();bucket_counts={}
    def add(row):
        text_hash=hashlib.sha256(' '.join(words(row['primary'])).encode()).hexdigest()
        if len(selected)>=size:return False
        if row['token'] in {s['token'] for s in selected} or text_hash in seen_text or counts[row['orientation']]>=size//2:return False
        selected.append(row);counts[row['orientation']]+=1;seen_text.add(text_hash)
        bucket_counts[row['bucket']]=bucket_counts.get(row['bucket'],0)+1
        return True
    # Diversify rather than select only one category of the largest diff score.
    for bucket,quota in [('technical',size//2),('number_negation',size//5),('lexical',size//3)]:
        for row in candidates:
            if row['bucket']==bucket and bucket_counts.get(bucket,0)<quota:add(row)
    for row in candidates:
        if len(selected)>=size:break
        add(row)
    return selected,{'eligible':len(candidates),'selected':len(selected),'version':VERSION,
                     'balanced':counts[0]==counts[1],'selection_biased':True,
                     'buckets':bucket_counts,'total_audio_seconds':round(sum(r['duration'] for r in selected),3)}


def install(c,size=30):
    c.execute('CREATE TABLE IF NOT EXISTS blind_review_sets(set_id TEXT NOT NULL,token TEXT NOT NULL,reasons_json TEXT NOT NULL,criteria_json TEXT NOT NULL,PRIMARY KEY(set_id,token))')
    count=c.execute('SELECT count(*) FROM blind_review_sets WHERE set_id=?',(VERSION,)).fetchone()[0]
    if count:return {'status':'already_fixed','selected':count,'version':VERSION}
    selected,summary=select(c,size)
    if len(selected)!=size or not summary['balanced']:raise ValueError('Insufficient balanced challenging examples')
    with c:
        for row in selected:
            c.execute('INSERT INTO blind_review_sets VALUES(?,?,?,?)',(VERSION,row['token'],json.dumps(row['reasons'],ensure_ascii=False),json.dumps({k:row[k] for k in ['ratio','changed_words','bucket','duration']},ensure_ascii=False)))
    return {'status':'installed',**summary}
