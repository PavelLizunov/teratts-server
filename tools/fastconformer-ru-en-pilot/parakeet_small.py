"""Pinned English-only 110M hybrid CTC branch; original F32 export, no hints."""
import argparse

from english_fc import prepare, cell
from mms_pair import supervise, LIMITS

ORIGINAL_SHA='1e6b5c3bcaa390b479bd8112512ede515d2ef5b61495568f2c266d6d5e680c3a'
EXPORT_SHA='936806cf3dd0db5aba53f8c7410bb5632d7a8ad6b2c51009f5e4fc0890ec76bf'


if __name__=='__main__':
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='mode',required=True)
    prep=sub.add_parser('prepare');prep.add_argument('--model',required=True)
    c=sub.add_parser('cell')
    for name in ('model','wav','audio-sha256','output'):c.add_argument('--'+name,required=True)
    batch=sub.add_parser('pilot');batch.add_argument('manifest');a=p.parse_args()
    if a.mode=='prepare':prepare(a,ORIGINAL_SHA,EXPORT_SHA,english_case='original')
    elif a.mode=='cell':cell(a)
    else:supervise(a,cell_script=__file__,limits={**LIMITS,'rss_mib':4096},batch_seconds=900)
