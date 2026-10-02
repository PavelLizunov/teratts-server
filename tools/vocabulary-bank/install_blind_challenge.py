"""Explicit new blinded diagnostic set; immutable existing mapping/votes retained."""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import shutil
import stat

import blind_challenge_set as challenge
import vocabulary_review as review
import vocabulary_bank as bank
from voice_corpus import MAX_BYTES,MIN_FREE_BYTES


def install(root):
    root=Path(root);fd=os.open(root/'.lock',os.O_RDWR|os.O_NOFOLLOW);old=os.umask(0o077)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);total=0
        for p in root.iterdir():
            info=p.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError('Unsafe corpus')
            total+=info.st_size
        size=(root/bank.DB_NAME).stat().st_size;reserve=size+bank.RESERVE
        if total+reserve>MAX_BYTES or shutil.disk_usage(root).free-reserve<MIN_FREE_BYTES:raise RuntimeError('Headroom unavailable')
        with contextlib.closing(review.connect(root,write=True)) as c:
            page=c.execute('pragma page_size').fetchone()[0];c.execute(f'pragma max_page_count={min(bank.DB_LIMIT,size+bank.RESERVE//4)//page}')
            return challenge.install(c)
    finally:os.close(fd);os.umask(old)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();print(json.dumps(install(a.root)))
