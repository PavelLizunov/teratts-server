"""Attribute one English quantization change with frozen native routing/decoder."""
import argparse
from ctc_lm import pilot
from russian_mixed import cell
from russian_boundary import NativeWordRules

if __name__=='__main__':
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='mode',required=True);c=sub.add_parser('cell')
    for key in ('root','model','receipt','context-receipt','output'):c.add_argument('--'+key,required=True)
    p=sub.add_parser('pilot');p.add_argument('manifest');args=parser.parse_args()
    if args.mode=='cell':cell(args,rules_type=NativeWordRules,english_model='parakeet-english-int8',english_results='results-parakeet-int8-v1')
    else:pilot(args,cell_script=__file__)
