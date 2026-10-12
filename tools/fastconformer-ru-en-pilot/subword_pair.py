"""Open English SentencePiece + Russian character CTC on native head events.

Auxiliary text supplies alignment only. No transcript replacements, acoustic
reruns, probability interpolation or character-only reduction of English vocab.
"""
import argparse
from functools import lru_cache
import json
import math
from pathlib import Path
import resource
import subprocess
import time
import unicodedata

from ctc_context import NEG, logadd
from current_head_alignment import align
from decoder import ContextBias
from mms_pair import HINTS, digest, save
from run import Guard

RU_OFFSET = 1025
BOUNDARY = -1  # Context-only symbol, never an acoustic/output token.


def auxiliary_labels(text, processor, ru_vocab, english_case='original'):
    words, pending = [], ''
    for c in text:
        if c.isspace() or (unicodedata.category(c)[0] in 'PZS' and c != "'"):
            if pending: words.append(pending); pending = ''
        else: pending += c
    if pending: words.append(pending)
    sequence, provenance, switches = [], [], set()
    previous = None
    for word in words:
        ru_word = word.lower()
        ru_ok = all(c in ru_vocab and c != ' ' for c in ru_word)
        en_word = word.lower() if english_case == 'lower' else word
        en_ids = processor.encode(en_word)
        en_ok = bool(en_ids) and 0 not in en_ids and processor.decode(en_ids) == en_word
        if ru_ok == en_ok:
            raise ValueError('Word not uniquely representable by current trained heads: '+word)
        lang = 'rus' if ru_ok else 'eng'
        begin = len(sequence)
        if lang != previous and previous is not None: switches.add(begin)
        if lang == 'rus':
            if previous is not None: sequence.append(('rus', ru_vocab[' ']))
            ids = [ru_vocab[c] for c in ru_word]
        else:
            ids = en_ids
            if not processor.id_to_piece(ids[0]).startswith('▁'):
                raise ValueError('English word lacks published start marker')
        sequence.extend((lang,t) for t in ids)
        provenance.append({'original':word,'head':lang,'first_label':begin,'last_label':len(sequence)-1})
        previous = lang
    if not sequence: raise ValueError('Empty auxiliary proposal')
    return sequence, provenance, switches


class TokenRules:
    def __init__(self, en_tokens, ru_tokens, processor, english_case='original'):
        self.tokens = {i:p for i,p in en_tokens.items() if 0 < i < 1024}
        self.tokens.update({RU_OFFSET+i:p for i,p in ru_tokens.items() if i != 33})
        self.heads = {'eng':{i:i for i in self.tokens if i<RU_OFFSET},
                      'rus':{i:i-RU_OFFSET for i in self.tokens if i>=RU_OFFSET}}
        self.language = {t:('eng' if t<RU_OFFSET else 'rus') for t in self.tokens}
        self.starts = {t for t,p in self.tokens.items() if p.startswith('▁') or p == ' '}
        self.closes = {t for t,p in self.tokens.items() if not p.replace('▁','') or p==' ' or unicodedata.category(p[-1])[0] in 'PZS'}
        self.paths = []
        self.hint_receipts = []
        for hint in HINTS:
            ids = processor.encode(hint.lower() if english_case == 'lower' else hint)
            if 0 in ids: raise ValueError('Unrepresentable name hint')
            symbols = [s for token in ids for s in self.symbols(token)] + [BOUNDARY]
            self.paths.append(symbols)
            self.hint_receipts.append({'hint':hint,'token_ids':ids,'context_symbols':symbols})

    def symbols(self, token):
        piece = self.tokens[token]
        if piece in ('▁',' '): return [BOUNDARY]
        symbols = ([BOUNDARY] if token in self.starts else []) + [token]
        if token in self.closes: symbols.append(BOUNDARY)
        return symbols

    def allows(self, prefix, token):
        if token not in self.tokens: return False
        if not prefix: return self.language[token]=='rus' or token in self.starts
        last = prefix[-1]
        return (self.language[last]==self.language[token] or last in self.closes or token in self.starts)

    def text(self, prefix):
        return ''.join(self.tokens[t] for t in prefix).replace('▁',' ').strip()


def decode(events, rules, bonus, check, prefix_scorer=None):
    graph = ContextBias(rules.paths if bonus else (),bonus)
    @lru_cache(maxsize=100000)
    def bias(prefix):
        if not prefix: return 0., ()
        score,state = bias(prefix[:-1])
        for symbol in rules.symbols(prefix[-1]):
            delta,state = graph.step(state,symbol);score += delta
        return score,state
    current = {(): (0.,NEG)}
    for event in events:
        check()
        lang,row = event['head'],event['log_probs']
        blank = 1024 if lang=='eng' else 33
        following = {}
        def add(prefix,pb=NEG,pnb=NEG):
            old_b,old_nb = following.get(prefix,(NEG,NEG))
            following[prefix] = logadd(old_b,pb),logadd(old_nb,pnb)
        for prefix,(pb,pnb) in current.items():
            total=logadd(pb,pnb)
            add(prefix,pb=total+float(row[blank]))
            last=prefix[-1] if prefix else None
            for token,local in rules.heads[lang].items():
                lp=float(row[local])
                if last==token:
                    add(prefix,pnb=pnb+lp)
                    if rules.allows(prefix,token):add((*prefix,token),pnb=pb+lp)
                elif rules.allows(prefix,token):add((*prefix,token),pnb=total+lp)
        candidates=list(following)
        if prefix_scorer is not None:
            candidates=sorted(candidates,key=lambda p:logadd(*following[p])+bias(p)[0]+prefix_scorer.estimate(p),reverse=True)[:prefix_scorer.prebeam]
            prefix_scorer.prepare(candidates)
        current={p:following[p] for p in sorted(candidates,key=lambda p:logadd(*following[p])+bias(p)[0]+(prefix_scorer.credit(p) if prefix_scorer is not None else 0.),reverse=True)[:32]}
    if prefix_scorer is not None:prefix_scorer.prepare(list(current),final=True)
    result=[]
    for prefix,masses in current.items():
        acoustic=logadd(*masses)
        if not math.isfinite(acoustic):continue
        credit,state=bias(prefix)
        delta,state=graph.step(state,BOUNDARY)
        credit += delta+graph.finalize(state)
        raw=rules.text(prefix)
        violations=[i for i,t in enumerate(prefix) if not rules.allows(prefix[:i],t)]
        if violations:raise ValueError('Invalid trained-head word path')
        lm=prefix_scorer.receipt(prefix) if prefix_scorer is not None else {}
        result.append({'token_ids':list(prefix),'raw_pieces':[rules.tokens[t] for t in prefix],
                       'raw_text':raw,'postprocessed_text':raw,'native_ctc_logsum':acoustic,
                       'context_credit':credit,'total_score':acoustic+credit+lm.get('lm_credit',0.),'within_word_violations':violations,
                       'head_counts':{lang:sum(rules.language[t]==lang for t in prefix) for lang in rules.heads},**lm})
    return {'hypotheses':sorted(result,key=lambda r:r['total_score'],reverse=True)[:5],
            'beam':32,'acoustic_candidates':'all trained non-special IDs of current head',
            'hint_bonus':bonus,'context_boundary_marker_is_not_output':True,
            'hint_paths':rules.hint_receipts if bonus else []}


def main(args, alignment_fn=None):
    import numpy as np
    import sentencepiece as spm
    rp,ep,pp,output=map(Path,(args.russian,args.english,args.proposals,args.output))
    alignment_path=output.with_name(output.stem+'-alignment.json')
    if output.exists() or alignment_path.exists():raise FileExistsError('Consumed or unknown subword-pair cell')
    start=time.monotonic();guard=Guard(180,1536)
    result={'status':'failed','variants':{},'audio_or_encoder_rerun':False,'probability_interpolation':False,
            'per_region_decoders':False,'proposal_text_used_by_final_decoder':False,'postprocessing':'none',
            'source_commit':subprocess.check_output(['git','-C',str(Path(__file__).parent),'rev-parse','HEAD'],text=True).strip()}
    try:
        ru,en,proposal=(json.loads(p.read_text()) for p in (rp,ep,pp))
        if len({ru['audio_sha256'],en['audio_sha256'],proposal['audio_sha256']})!=1:raise ValueError('Mixed recordings')
        for path,receipt in ((rp,ru),(ep,en)):
            if digest(path.with_suffix('.npz'))!=receipt['retained_logits_sha256']:raise ValueError('Changed native array')
        em=Path(args.english_model);prepared=json.loads((em/'prepared.json').read_text())
        if digest(em/'prepared.json')!=en['prepared_sha256'] or digest(em/'tokenizer.model')!=prepared['tokenizer_sha256']:raise ValueError('Changed trained English tokenizer')
        processor=spm.SentencePieceProcessor(model_file=str(em/'tokenizer.model'))
        en_tokens={int(i):p for i,p in prepared['vocab'].items()}
        rm=Path(args.russian_model);assets=json.loads((rm/'download-receipt.json').read_text())
        if digest(rm/'download-receipt.json')!=ru['asset_receipt_sha256'] or digest(rm/'tokens.txt')!=next(r['sha256'] for r in assets['files'] if r['name']=='tokens.txt'):raise ValueError('Changed trained Russian map')
        ru_tokens={int(s.rsplit(' ',1)[1]):s.rsplit(' ',1)[0] for s in (rm/'tokens.txt').read_text().splitlines()}
        ru_vocab={p:i for i,p in ru_tokens.items() if i!=33}
        english_case=prepared.get('english_case','original')
        if english_case not in ('original','lower'):raise ValueError('Unsupported trained tokenizer case convention')
        sequence,words,switches=auxiliary_labels(proposal['variants']['name-context']['hypotheses'][0]['raw_text'],processor,ru_vocab,english_case)
        with np.load(rp.with_suffix('.npz')) as file:rlp=file['log_probs'].astype(np.float64)
        with np.load(ep.with_suffix('.npz')) as file:elp=file['log_probs'].astype(np.float64)
        elp[:,0]=-np.inf;elp-=np.logaddexp.reduce(elp,axis=1,keepdims=True)
        events=[]
        for lang,array,stride,origin in (('eng',elp,1280,0.),('rus',rlp,640,159.5)):
            for i,row in enumerate(array):events.append({'head':lang,'native_frame':i,'center_s':(stride*i+origin)/16000,'log_probs':row})
        events.sort(key=lambda e:e['center_s'])
        if alignment_fn is None:
            selected,alignment=align(events,sequence,{'eng':1024,'rus':33},{'eng':processor.piece_to_id('▁'),'rus':0},guard.check,
                                     stride_weights={'eng':2.,'rus':1.},switch_indices=switches)
        else:
            selected,alignment=alignment_fn(events,sequence,guard.check)
        result.update(audio_sha256=ru['audio_sha256'],russian_receipt_sha256=digest(rp),english_receipt_sha256=digest(ep),
                      proposals_sha256=digest(pp),fixed_proposal_selection='name-context rank1',
                      trained_head_offsets={'eng':0,'rus':RU_OFFSET},native_rows={l:sum(e['head']==l for e in selected) for l in ('eng','rus')})
        alignment.update(label_path=sequence,proposal_words=words,**{k:v for k,v in result.items() if k not in ('status','variants')})
        save(alignment_path,alignment);result.update(alignment_sha256=digest(alignment_path),alignment_s=time.monotonic()-start)
        rules=TokenRules(en_tokens,ru_tokens,processor,english_case)
        for name,bonus in (('no-context',0.),('context',2.5)):
            before=time.monotonic();value=decode(selected,rules,bonus,guard.check)
            if not value['hypotheses']:raise ValueError('No finite open path')
            value['decode_s']=time.monotonic()-before;save(output.with_name(output.stem+'-'+name+'.json'),value)
            result['variants'][name]=value;print(name,value['hypotheses'][0]['raw_text'],flush=True)
        result['status']='success'
    except Exception as error:result['error']=type(error).__name__+': '+str(error);raise
    finally:
        result.update(elapsed_s=time.monotonic()-start,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,guard=guard.receipt());save(output,result)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for key in ('russian','english','proposals','russian-model','english-model','output'):parser.add_argument('--'+key,required=True)
    main(parser.parse_args())
