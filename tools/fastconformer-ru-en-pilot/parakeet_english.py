"""Pinned English-only Parakeet CTC 0.6B, not production multilingual TDT.

Shares verified NeMo frontend and one-whole-recording execution with English FC.
"""
import argparse

from english_fc import prepare, cell
from mms_pair import supervise

ORIGINAL_SHA = 'bc01f3f8f0098b72b6f461d36b01f45a4bc00a2973ab840bd31edab96e605fc9'
EXPORT_SHA = '4d2866ba5d0162d870776bad53991f29dac04238d1d7b1e02874b43ebc5c702a'
EXTERNAL_SHA = 'e1951d4e0bdcde6e3059b8796140d98d73b3b9c7bee1adbc60505ceb09b9473f'

if __name__ == '__main__':
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='mode',required=True)
    p=sub.add_parser('prepare');p.add_argument('--model',required=True)
    c=sub.add_parser('cell')
    for key in ('model','wav','audio-sha256','output'):c.add_argument('--'+key,required=True)
    p=sub.add_parser('pilot');p.add_argument('manifest');args=parser.parse_args()
    if args.mode=='prepare':prepare(args,ORIGINAL_SHA,EXPORT_SHA,EXTERNAL_SHA,english_case='lower')
    elif args.mode=='cell':cell(args)
    else:supervise(args,cell_script=__file__)
