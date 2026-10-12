"""Frozen text probability in the strict two-specialist acoustic word graph.

Decoder-only: never load audio or an acoustic model. Raw acoustic pieces retain
publisher casing; lowercase copies are used only for deterministic LM scoring.
"""
import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import time

from ctc_lm import LanguageScorer, PARAMETERS, pilot
from mms_pair import LANGS, digest, save
from mms_word_graph import search
from run import Guard
from specialist_pair import MODELS


def cell(args):
    import numpy as np
    root, parent, output = Path(args.root), Path(args.receipt), Path(args.output)
    if output.exists():
        raise FileExistsError('Consumed specialist LM cell')
    started = time.monotonic()
    guard = Guard(PARAMETERS['seconds'], PARAMETERS['rss_mib'])
    scorer = None
    result = {'status': 'failed', 'parameters': PARAMETERS, 'variants': {},
              'encoder_rerun': False, 'audio_input': False, 'lm_generates_text': False,
              'allowed_trained_heads': list(LANGS), 'semantic_language_guarantee': False,
              'calibrated_language_detection': False, 'postprocessing': 'none',
              'lm_scoring_normalization': 'published EN uppercase to lowercase, delimiter to space; output untouched',
              'source_commit': subprocess.check_output(['git', '-C', str(Path(__file__).parent), 'rev-parse', 'HEAD'], text=True).strip(),
              'host': os.uname().nodename}
    try:
        original = json.loads(parent.read_text())
        context = json.loads(Path(args.context_receipt).read_text())
        if context['parent_sha256'] != digest(parent) or not context['whole_word_context'] or context['score'] != 2.5:
            raise ValueError('Wrong completed whole-word context receipt')
        arrays, vocabs, pieces, origins = {}, {}, {}, {}
        offset = 0
        for lang in LANGS:
            folder = root / 'alternative-methods/specialist-pair' / lang
            assets = json.loads((folder / 'download-receipt.json').read_text())
            repository, revision, size = MODELS[lang]
            if assets['revision'] != revision or original['heads'][lang]['revision'] != revision:
                raise ValueError('Wrong retained specialist revision')
            vpath = folder / 'vocab.json'
            expected = next(row['sha256'] for row in assets['files'] if row['name'] == 'vocab.json')
            if digest(vpath) != expected:
                raise ValueError('Changed published output vocabulary')
            vocab = json.loads(vpath.read_text())
            if vocab != original['heads'][lang]['vocab'] or len(vocab) != size:
                raise ValueError('Retained vocabulary provenance mismatch')
            vocabs[lang] = vocab
            path = parent.with_name(parent.stem + '-' + lang + '.npz')
            if digest(path) != original['heads'][lang]['retained_logits_sha256']:
                raise ValueError('Retained specialist logits changed')
            with np.load(path) as file:
                lp = file['log_probs'].astype(np.float64)
            if lp.shape[1] != size or not np.isfinite(lp).all():
                raise ValueError('Invalid saved specialist logits')
            lp[:, [vocab['<s>'], vocab['</s>'], vocab['<unk>']]] = -np.inf
            lp -= np.logaddexp.reduce(lp, axis=1, keepdims=True)
            arrays[lang] = lp
            for piece, token in vocab.items():
                if piece in ('<pad>', '<s>', '</s>', '<unk>'):
                    continue
                pieces[offset + token] = ' ' if piece == '|' else piece.lower()
                origins[offset + token] = {'head': lang, 'local_id': token, 'raw_piece': piece}
            offset += len(vocab)
        if arrays['eng'].shape[0] != arrays['rus'].shape[0]:
            raise ValueError('Mismatched whole-recording frame grids')
        result.update(audio_sha256=original['audio_sha256'], parent_sha256=digest(parent),
                      context_parent_sha256=digest(args.context_receipt), numerical_provenance=origins,
                      reserved_mask='per-head BOS/EOS/UNK suppressed, own blank retained and renormalized')
        scorer = LanguageScorer(Path(args.model), pieces, guard.check)
        result['lm_loading'] = scorer.load_receipt
        for name, score in (('no-context', 0.), ('context', 2.5)):
            before = time.monotonic()
            value = search(arrays, vocabs, score, guard.check, hint_case='upper',
                           whole_word_context=True, prefix_scorer=scorer)
            if not value['hypotheses']:
                raise ValueError('No finite pair hypothesis')
            for hypothesis in value['hypotheses']:
                if any(token not in origins for token in hypothesis['token_ids']):
                    raise ValueError('Forbidden trained-head ID')
            value['best_score_consistency'] = scorer.observe_best_score(tuple(value['hypotheses'][0]['token_ids']))
            value['decode_s'] = time.monotonic() - before
            save(output.with_name(output.stem + '-' + name + '.json'), value)
            result['variants'][name] = value
            print(name, value['hypotheses'][0]['raw_text'], flush=True)
        result['status'] = 'success'
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        if scorer:
            result['lm_work'] = {'forward_calls': scorer.forward_calls, 'scored_sequences': scorer.scored_sequences,
                                 'processed_suffix_tokens': scorer.processed_suffix_tokens,
                                 'peak_kv_cache_bytes': scorer.peak_cache_bytes}
        result.update(elapsed_s=time.monotonic() - started,
                      peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                      guard=guard.receipt())
        save(output, result)
        print(json.dumps({k: v for k, v in result.items() if k not in ('variants', 'numerical_provenance')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='mode', required=True)
    c = sub.add_parser('cell')
    for key in ('root', 'model', 'receipt', 'context-receipt', 'output'):
        c.add_argument('--' + key, required=True)
    p = sub.add_parser('pilot')
    p.add_argument('manifest')
    args = parser.parse_args()
    if args.mode == 'cell': cell(args)
    else: pilot(args, cell_script=__file__)
