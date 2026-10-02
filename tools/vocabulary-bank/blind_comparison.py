"""Blind server-side balanced randomization. Public responses never include mapping."""
import hashlib
import json
import secrets

TOKEN_LENGTH=32


def initialize(c):
    c.execute('CREATE TABLE IF NOT EXISTS blind_assignments(token TEXT PRIMARY KEY,audio_sha TEXT UNIQUE NOT NULL,option1_primary INTEGER NOT NULL,display_order INTEGER NOT NULL)')
    rows=c.execute('SELECT audio_sha FROM model_comparisons WHERE audio_sha NOT IN(SELECT audio_sha FROM blind_assignments)').fetchall()
    if not rows:return
    rng=secrets.SystemRandom();rng.shuffle(rows)
    ones,zeros=c.execute('SELECT coalesce(sum(option1_primary),0),count(*)-coalesce(sum(option1_primary),0) FROM blind_assignments').fetchone()
    flags=[]
    for _ in rows:
        if ones<zeros:flag=1
        elif zeros<ones:flag=0
        else:flag=rng.randrange(2)
        flags.append(flag);ones+=flag;zeros+=1-flag
    rng.shuffle(flags)
    maximum=c.execute('SELECT coalesce(max(display_order),-1) FROM blind_assignments').fetchone()[0]
    with c:
        for i,((sha,),flag) in enumerate(zip(rows,flags)):
            c.execute('INSERT INTO blind_assignments VALUES(?,?,?,?)',(secrets.token_hex(16),sha,flag,maximum+i+1))


def private_row(c,token):
    if not isinstance(token,str) or len(token)!=32 or any(ch not in '0123456789abcdef' for ch in token):raise ValueError('Invalid blind key')
    row=c.execute('SELECT b.token,b.audio_sha,b.option1_primary,b.display_order,m.* FROM blind_assignments b JOIN model_comparisons m ON m.audio_sha=b.audio_sha WHERE b.token=?',(token,)).fetchone()
    if not row:raise ValueError('Blind card not found')
    return row


def revision(row):return hashlib.sha256(json.dumps(['blind-v1',row],ensure_ascii=False).encode()).hexdigest()


def resolve_choice(row,decision):
    if decision=='option1':return 'primary' if row[2] else 'candidate'
    if decision=='option2':return 'candidate' if row[2] else 'primary'
    return decision


def public_rows(c,query='',page=0,pending=True,filter='priority'):
    if filter not in ['priority','empty','technical','all'] or len(query)>100 or not 0<=page<=10000:raise ValueError('Invalid filter')
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='blind_assignments'").fetchone():raise ValueError('Blind review not initialized')
    condition='WHERE (instr(fold(m.primary_text),?)>0 OR instr(fold(m.candidate_text),?)>0)'
    if filter=='priority':condition+=' AND m.priority=1'
    elif filter=='empty':condition+=" AND m.category IN ('candidate_empty','primary_empty')"
    elif filter=='technical':condition+=' AND m.technical=1'
    feedback=bool(c.execute("SELECT 1 FROM sqlite_master WHERE name='feedback'").fetchone())
    if pending and feedback:condition+=" AND NOT EXISTS(SELECT 1 FROM feedback f WHERE f.target_kind='blind_comparison' AND f.target_key=b.token)"
    args=(query.casefold(),query.casefold())
    total=c.execute('SELECT count(*) FROM blind_assignments b JOIN model_comparisons m ON m.audio_sha=b.audio_sha '+condition,args).fetchone()[0]
    tokens=[r[0] for r in c.execute('SELECT b.token FROM blind_assignments b JOIN model_comparisons m ON m.audio_sha=b.audio_sha '+condition+' ORDER BY b.display_order LIMIT 10 OFFSET ?',(*args,page*10))]
    items=[]
    for token in tokens:
        row=private_row(c,token);flag=row[2];primary,candidate=row[5],row[6]
        decision=None
        if feedback:
            last=c.execute("SELECT decision,value FROM feedback WHERE target_kind='blind_comparison' AND target_key=? ORDER BY created_ns DESC LIMIT 1",(token,)).fetchone()
            if last:decision={'decision':last[0],'value':last[1]}
        category=row[10]
        neutral='empty' if category in ['candidate_empty','primary_empty'] else 'agreement' if category=='agreement' else 'difference'
        items.append({'key':token,'option1_text':primary if flag else candidate,'option2_text':candidate if flag else primary,
                      'duration_s':row[9],'category':neutral,'decision':decision,'revision':revision(row),
                      'blind':True,'training_approved':False})
    decisions={}
    if feedback:
        decisions=dict(c.execute("SELECT f.decision,count(*) FROM feedback f WHERE target_kind='blind_comparison' AND NOT EXISTS(SELECT 1 FROM feedback n WHERE n.target_kind=f.target_kind AND n.target_key=f.target_key AND n.created_ns>f.created_ns) GROUP BY f.decision"))
    return {'items':items,'total':total,'page':page,'page_size':10,'comparison_stats':{
        'unique_audio':c.execute('SELECT count(*) FROM blind_assignments').fetchone()[0],
        'priority_count':c.execute('SELECT count(*) FROM model_comparisons WHERE priority=1').fetchone()[0],
        'decisions':decisions,'blind':True,'diagnostic_selection_not_accuracy_sample':True}}
