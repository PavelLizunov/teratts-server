"""Carry native Russian predictor word closure through an English CTC insertion."""
import argparse

from ctc_lm import pilot
from russian_mixed import cell
from subword_pair import BOUNDARY, TokenRules


class NativeWordRules(TokenRules):
    formatting='explicit separator at accepted native-head word switch only; raw_piece_text preserved'

    def allows(self,prefix,token):
        if (token in self.tokens and prefix and self.language[prefix[-1]]=='rus'
                and self.language[token]=='eng' and prefix[-1] not in self.closes):return False
        if super().allows(prefix,token):return True
        if token not in self.tokens or self.language[token]!='rus' or not prefix or self.language[prefix[-1]]!='eng':return False
        previous=next((t for t in reversed(prefix) if self.language[t]=='rus'),None)
        return previous is None or previous in self.closes

    def can_leave_head(self,prefix,head,next_head):
        if head!='rus' or next_head!='eng':return True
        previous=next((t for t in reversed(prefix) if self.language[t]=='rus'),None)
        return previous is None or previous in self.closes

    def path_symbols(self,prefix):
        symbols=self.symbols(prefix[-1])
        if len(prefix)>1 and self.language[prefix[-1]]!=self.language[prefix[-2]] and (not symbols or symbols[0]!=BOUNDARY):symbols=[BOUNDARY,*symbols]
        return symbols

    def formatting_receipt(self,prefix):
        pieces=[self.tokens[t].replace('▁',' ') for t in prefix];separators=[];rendered=[]
        for i,piece in enumerate(pieces):
            if i and self.language[prefix[i]]!=self.language[prefix[i-1]] and not pieces[i-1][-1].isspace() and not piece[0].isspace():
                rendered.append(' ');separators.append(i)
            rendered.append(piece)
        return {'raw_piece_text':''.join(pieces),'postprocessed_text':''.join(rendered).strip(),
                'formatting_only_inserted_space_before_token_indices':separators}


if __name__=='__main__':
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='mode',required=True);c=sub.add_parser('cell')
    for key in ('root','model','receipt','context-receipt','output'):c.add_argument('--'+key,required=True)
    p=sub.add_parser('pilot');p.add_argument('manifest');args=parser.parse_args()
    if args.mode=='cell':cell(args,rules_type=NativeWordRules)
    else:pilot(args,cell_script=__file__)
