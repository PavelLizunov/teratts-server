"""Import completed immutable experiment evidence under shared corpus quota."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

import model_comparison_review as comparisons
import vocabulary_review as review
import vocabulary_bank as bank
from voice_corpus import MAX_BYTES,MIN_FREE_BYTES

EXPECTED_SUMMARY='b2c35c362c938c20de2633893630b5c53ce578c8891e72183bf3f112a1a69bab'


def import_summary(root,summary_path,expected=EXPECTED_SUMMARY):
    raw=Path(summary_path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('Experiment summary changed')
    records=comparisons.build_records(json.loads(raw));root=Path(root)
    fd=os.open(root/'.lock',os.O_RDWR|os.O_NOFOLLOW);old=os.umask(0o077)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        total=0
        for p in root.iterdir():
            info=p.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError('Unsafe corpus entry')
            total+=info.st_size
        size=(root/bank.DB_NAME).stat().st_size;reserve=size+bank.RESERVE
        if total+reserve>MAX_BYTES or shutil.disk_usage(root).free-reserve<MIN_FREE_BYTES:raise RuntimeError('Corpus headroom unavailable')
        with contextlib.closing(review.connect(root,write=True)) as c:
            page=c.execute('pragma page_size').fetchone()[0]
            c.execute(f'pragma max_page_count={min(bank.DB_LIMIT,size+bank.RESERVE//4)//page}')
            count=comparisons.import_records(c,records)
            return {'imported':count,'unique_comparisons':len(records),'priority':sum(r['priority'] for r in records),
                    'old_feedback_preserved':True,'summary_sha256':expected,'training_started':False}
    finally:os.close(fd);os.umask(old)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('summary',type=Path);a=p.parse_args()
    print(json.dumps(import_summary(a.root,a.summary)))
