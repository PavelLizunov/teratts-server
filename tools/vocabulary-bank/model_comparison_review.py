"""Read-only experiment evidence plus explicit human preferences, not model promotion."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import secrets

MODEL_SHA='3fc991d3badad7277c11030a7519832cddaf2057aafed6d4b25147e953a070b1'
MANIFEST_SHA='18deafef165d25d8420b17aa85c5e89a1c31326664c7089a1daa15d48b01e77f'
TECH=re.compile(r'omarch|[аоу]марч|умрч|github|г[ие]тх|plugin|плаг|контриб|contributor|\b(?:git|pull|push|sudo|linux)\b|репозит|коммит|пул|пуш|чат',re.I)


def ensure_schema(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS model_comparisons(
      audio_sha TEXT PRIMARY KEY, primary_text TEXT NOT NULL, candidate_text TEXT NOT NULL,
      sample_ids TEXT NOT NULL, source_count INTEGER NOT NULL, duration REAL NOT NULL,
      category TEXT NOT NULL, technical INTEGER NOT NULL, priority INTEGER NOT NULL,
      agreement_ratio REAL NOT NULL, model_sha TEXT NOT NULL, manifest_sha TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS comparison_priority ON model_comparisons(priority,category);''')


def build_records(summary):
    if (not summary.get('all_manifest_results_successful') or summary.get('model_sha256')!=MODEL_SHA
            or summary.get('frozen_manifest_sha256')!=MANIFEST_SHA):raise ValueError('Unverified completed experiment')
    records=[];seen=set()
    for result in summary['results']:
        sha=result['audio_sha256']
        if not re.fullmatch('[a-f0-9]{64}',sha) or sha in seen or result['status']!='completed':raise ValueError('Duplicate/invalid comparison')
        seen.add(sha);compared=result['comparisons'];primary=compared[0].get('baseline_raw','');candidate=result['candidate_text']
        if not isinstance(primary,str) or not isinstance(candidate,str):raise ValueError('Invalid text')
        if primary.strip() and not candidate.strip():category='candidate_empty'
        elif not primary.strip() and candidate.strip():category='primary_empty'
        elif compared[0].get('same_normalized_text'):category='agreement'
        else:category=compared[0].get('category','substantial_difference')
        records.append({'sha':sha,'primary':primary,'candidate':candidate,'samples':[x['sample_id'] for x in compared],
            'source_count':len(compared),'duration':result['duration_s'],'category':category,
            'technical':bool(TECH.search(primary+' '+candidate)),
            'ratio':compared[0].get('token_agreement_ratio',0),'priority':0})
    if len(records)!=summary['total_unique_audio']:raise ValueError('Coverage mismatch')
    # Diagnostic set, NOT representative quality score. Spread empty durations.
    empty=sorted([r for r in records if r['category']=='candidate_empty'],key=lambda r:(r['duration'],r['sha']))
    selected=[]
    if empty:
        indices=sorted(set(round(i*(len(empty)-1)/7) for i in range(min(8,len(empty)))))
        selected.extend(empty[i] for i in indices)
    selected.extend(sorted([r for r in records if r['category']=='primary_empty'],key=lambda r:r['sha'])[:1])
    technical=sorted([r for r in records if r['technical'] and r['category']=='substantial_difference'],key=lambda r:(r['ratio'],r['sha']))
    selected.extend(technical[:8])
    selected.extend(sorted([r for r in records if r['category']=='agreement' and r['primary'].strip() and r['candidate'].strip()],key=lambda r:r['sha'])[:3])
    ids={r['sha'] for r in selected}
    if len(ids)<20:
        for r in sorted(records,key=lambda r:(r['category']=='agreement',r['sha'])):
            if len(ids)>=20:break
            ids.add(r['sha'])
    for r in records:r['priority']=int(r['sha'] in ids)
    return records


def import_records(c,records):
    ensure_schema(c);added=0
    with c:
        for r in records:
            old=c.execute('SELECT primary_text,candidate_text,model_sha,manifest_sha FROM model_comparisons WHERE audio_sha=?',(r['sha'],)).fetchone()
            expected=(r['primary'],r['candidate'],MODEL_SHA,MANIFEST_SHA)
            if old:
                if old!=expected:raise ValueError('Existing comparison changed')
                c.execute('UPDATE model_comparisons SET priority=? WHERE audio_sha=?',(r['priority'],r['sha']))
                continue
            c.execute('INSERT INTO model_comparisons VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (r['sha'],r['primary'],r['candidate'],json.dumps(r['samples']),r['source_count'],r['duration'],r['category'],r['technical'],r['priority'],r['ratio'],MODEL_SHA,MANIFEST_SHA))
            added+=1
    initialize_blind(c)
    return added


def initialize_blind(c):
    from blind_comparison import initialize
    initialize(c)


def exists(c):return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_comparisons'").fetchone())


def comparison_row(c,key):
    if not re.fullmatch('[a-f0-9]{64}',key) or not exists(c):raise ValueError('Invalid comparison key')
    row=c.execute('SELECT * FROM model_comparisons WHERE audio_sha=?',(key,)).fetchone()
    if not row:raise ValueError('Comparison not found')
    return row


def rows(c,query='',page=0,pending=True,filter='priority'):
    if filter not in ['priority','empty','technical','all'] or len(query)>100 or not 0<=page<=10000:raise ValueError('Invalid comparison filter')
    if not exists(c):return {'items':[],'total':0,'page':page,'page_size':10,'comparison_stats':{}}
    condition="WHERE (instr(fold(m.primary_text),?)>0 OR instr(fold(m.candidate_text),?)>0)"
    if filter=='priority':condition+=' AND m.priority=1'
    elif filter=='empty':condition+=" AND m.category IN ('candidate_empty','primary_empty')"
    elif filter=='technical':condition+=' AND m.technical=1'
    feedback=bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feedback'").fetchone())
    if pending and feedback:condition+=" AND NOT EXISTS(SELECT 1 FROM feedback f WHERE f.target_kind='model_comparison' AND f.target_key=m.audio_sha)"
    args=(query.casefold(),query.casefold())
    total=c.execute('SELECT count(*) FROM model_comparisons m '+condition,args).fetchone()[0]
    data=c.execute('SELECT m.* FROM model_comparisons m '+condition+" ORDER BY m.priority DESC,CASE m.category WHEN 'candidate_empty' THEN 0 WHEN 'primary_empty' THEN 1 ELSE 2 END,m.audio_sha LIMIT 10 OFFSET ?",(*args,page*10)).fetchall()
    items=[]
    for row in data:
        sha,primary,candidate,samples,sources,duration,category,technical,priority,ratio,model,manifest=row
        decision=None
        if feedback:
            prior=c.execute("SELECT decision,value FROM feedback WHERE target_kind='model_comparison' AND target_key=? ORDER BY created_ns DESC LIMIT 1",(sha,)).fetchone()
            if prior:decision={'decision':prior[0],'value':prior[1]}
        revision=hashlib.sha256(json.dumps(['model_comparison',row],ensure_ascii=False).encode()).hexdigest()
        items.append({'key':sha,'primary':primary,'candidate':candidate,'sample_ids':json.loads(samples),
            'source_count':sources,'duration_s':duration,'category':category,'technical':bool(technical),
            'priority':bool(priority),'decision':decision,'revision':revision,
            'human_gold':False,'training_approved':False})
    totals=dict(c.execute('SELECT category,count(*) FROM model_comparisons GROUP BY category'))
    chosen={}
    if feedback:
        chosen=dict(c.execute("SELECT f.decision,count(*) FROM feedback f WHERE target_kind='model_comparison' AND NOT EXISTS(SELECT 1 FROM feedback n WHERE n.target_kind=f.target_kind AND n.target_key=f.target_key AND n.created_ns>f.created_ns) GROUP BY f.decision"))
    return {'items':items,'total':total,'page':page,'page_size':10,'comparison_stats':{'unique_audio':sum(totals.values()),
        'categories':totals,'priority_count':c.execute('SELECT count(*) FROM model_comparisons WHERE priority=1').fetchone()[0],
        'decisions':chosen,'diagnostic_selection_not_accuracy_sample':True}}


def frozen_audio_path(root,sha):
    if not re.fullmatch('[a-f0-9]{64}',sha):raise ValueError('Invalid audio SHA')
    return Path(root).parent/'nemotron-full/run-20261002/audio'/(sha+'.wav')
