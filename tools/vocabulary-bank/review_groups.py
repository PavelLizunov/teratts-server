"""Conservative view-only review deduplication. No evidence deletion."""
import hashlib
import json
import re


def signature(row,include_canonical=True):
    # tuple: id,source,stage,canonical,start,end,surface,reason,label,text,sample,digest
    text=row[9];matches=list(re.finditer(r'[^\W_]+',text,re.UNICODE))
    words=[m.group().casefold().replace('ё','е') for m in matches]
    indices=[i for i,m in enumerate(matches) if m.start()<row[5] and m.end()>row[4]]
    # Unknown sample never merges with another document. Position is a token index,
    # not merely surface text; repetitions in the same utterance remain separate.
    origin=row[10] if row[10] else ('document',row[1],row[2])
    return (row[3] if include_canonical else None,origin,tuple(words),tuple(indices),
            row[6].casefold().replace('ё','е'))


def latest(connection,identity):
    exists=connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feedback'").fetchone()
    if not exists:return None
    row=connection.execute("SELECT decision,value,request_id,created_ns FROM feedback WHERE target_kind='name_occurrence' AND target_key=? ORDER BY created_ns DESC LIMIT 1",(str(identity),)).fetchone()
    return row


def rows_for(connection,canonical,limit=5001):
    return connection.execute("SELECT m.id,m.source,m.stage,m.canonical,m.start,m.end,m.surface,m.reason,m.label,d.text,d.sample_ref,d.text_hash FROM name_mentions m JOIN name_documents d ON d.source=m.source AND d.stage=m.stage WHERE m.canonical=? ORDER BY m.id DESC LIMIT ?",(canonical,limit)).fetchall()


def group_rows(connection,canonical):
    rows=rows_for(connection,canonical);truncated=len(rows)>5000;rows=rows[:5000]
    groups={}
    for row in rows:groups.setdefault(signature(row),[]).append(row)
    specialized=set()
    if canonical=='Разработка':
        for topic in ['GitHub','плагины']:
            specialized.update(signature(row,False) for row in rows_for(connection,topic,5000))
    result=[];routed=0
    for members in groups.values():
        if canonical=='Разработка' and signature(members[0],False) in specialized:
            routed+=len(members);continue
        members=sorted(members,key=lambda row:(row[2]!='stt_raw',row[0]))
        decisions=[latest(connection,row[0]) for row in members]
        observed={(d[0],d[1]) for d in decisions if d}
        conflict=len(observed)>1
        decision=next(({'decision':d[0],'value':d[1]} for d in decisions if d),None) if not conflict else None
        snapshot=[members,decisions]
        revision=hashlib.sha256(json.dumps(snapshot,ensure_ascii=False).encode()).hexdigest()
        result.append({'row':members[0],'members':members,'decisions':decisions,'decision':decision,
                       'conflict':conflict,'revision':revision})
    result.sort(key=lambda g:({'ambiguous':0,'suspected':1}.get(g['row'][8],2),-max(r[0] for r in g['members'])))
    return result,{'evidence_rows':len(rows),'grouped_cards':len(result),
                   'duplicate_stage_rows_hidden':sum(len(g['members'])-1 for g in result),
                   'routed_to_specific_queue':routed,'grouping_window_limited':truncated}


def for_row(connection,row):
    rows=rows_for(connection,row[3]);members=[candidate for candidate in rows if signature(candidate)==signature(row)]
    if not any(candidate[0]==row[0] for candidate in members):members.append(row)
    members=sorted(members,key=lambda r:(r[2]!='stt_raw',r[0]))
    decisions=[latest(connection,r[0]) for r in members]
    revision=hashlib.sha256(json.dumps([members,decisions],ensure_ascii=False).encode()).hexdigest()
    return members,revision
