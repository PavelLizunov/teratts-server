"""Append-only correction of misleading opening yes-clicks on Ну.

User clarification authorizes Ну as Ну, not Смотри. Original audit rows retained.
No/no-confidence/explicit custom and later human corrections are not touched.
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import time

import vocabulary_bank as bank
import vocabulary_review as review
from voice_corpus import MAX_BYTES,MIN_FREE_BYTES


def repair(root):
    root=Path(root);fd=os.open(root/'.lock',os.O_RDWR|os.O_NOFOLLOW)
    old=os.umask(0o077)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'status':'lock_busy','repaired':0}
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError('Unsafe lock')
        total=0
        for p in root.iterdir():
            info=p.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError('Unsafe corpus entry')
            total+=info.st_size
        size=(root/bank.DB_NAME).stat().st_size
        reserve=size+bank.RESERVE
        if total+reserve>MAX_BYTES or shutil.disk_usage(root).free-reserve<MIN_FREE_BYTES:
            return {'status':'headroom_skip','repaired':0}
        with contextlib.closing(review.connect(root,write=True)) as c:
            if not review.has_feedback(c):return {'status':'no_feedback','repaired':0}
            rows=c.execute("SELECT m.id,m.surface,f.request_id FROM name_mentions m JOIN feedback f ON f.target_kind='name_occurrence' AND f.target_key=cast(m.id as text) WHERE m.canonical='Смотри' AND fold(m.surface)='ну' AND f.decision='yes' AND NOT EXISTS(SELECT 1 FROM feedback n WHERE n.target_kind=f.target_kind AND n.target_key=f.target_key AND n.created_ns>f.created_ns)").fetchall()
            page_size=c.execute('pragma page_size').fetchone()[0]
            c.execute(f'pragma max_page_count={min(bank.DB_LIMIT,size+bank.RESERVE//4)//page_size}')
            with c:
                c.execute('CREATE TABLE IF NOT EXISTS feedback_context(request_id TEXT PRIMARY KEY,context_json TEXT NOT NULL)')
                for identity,surface,prior in rows:
                    rid='repair_opening_'+hashlib.sha256(prior.encode()).hexdigest()[:32]
                    if c.execute('select 1 from feedback where request_id=?',(rid,)).fetchone():continue
                    row=review.mention_row(c,identity)
                    c.execute('INSERT INTO feedback VALUES(?,?,?,?,?,?)',(rid,'name_occurrence',str(identity),'custom','Ну',time.time_ns()))
                    c.execute('INSERT INTO feedback_context VALUES(?,?)',(rid,json.dumps({'scope':'named_occurrence','canonical':'Смотри','resolved_word':'Ну','surface':surface,'text':row[9],'range':[row[4],row[5]],'source':row[1],'sample_id':row[10],'supersedes_request_id':prior,'reason':'user_clarified_misleading_opening_button','alias_approved':False},ensure_ascii=False)))
            return {'status':'repaired','repaired':len(rows),'original_history_preserved':True,'no_smotri_substitution':True}
    finally:os.close(fd);os.umask(old)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);args=p.parse_args()
    print(json.dumps(repair(args.root)))
