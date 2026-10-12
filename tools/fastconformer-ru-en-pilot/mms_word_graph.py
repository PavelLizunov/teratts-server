"""Word-state fusion on retained MMS outputs, with a separate blank per head.

No encoder call. The chosen head persists inside a word. This removes shared-
blank erasure, but does not calibrate independently trained language models.
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

from ctc_context import logadd, NEG
from decoder import ContextBias
from mms_pair import digest, save, LANGS, HINTS
from run import Guard


def search(arrays, vocab, score, check, hint_case='lower', whole_word_context=False):
    tokens, language, local, boundaries, delimiters, by_head = {}, {}, {}, set(), set(), {}
    offset = 0
    offsets = {}
    for lang in LANGS:
        offsets[lang] = offset
        by_head[lang] = []
        for piece, i in vocab[lang].items():
            if piece in ('<pad>', '<s>', '</s>', '<unk>'):
                continue
            token = offset + i
            tokens[token], language[token], local[token] = piece, lang, i
            by_head[lang].append(token)
            if piece == '|':
                delimiters.add(token)
            if piece == '|' or all(unicodedata.category(c)[0] in 'PZS' for c in piece):
                boundaries.add(token)
        offset += len(vocab[lang])
    # A name may follow a delimiter emitted by either trained head. The name
    # itself uses English numerical IDs; no duplicated string lookup occurs.
    if hint_case not in ('lower', 'upper'):
        raise ValueError('Unsupported published hint casing')
    paths = [[offsets[lang] + vocab[lang]['|'],
              *[vocab['eng']['|' if c == ' ' else c] for c in (h.lower() if hint_case == 'lower' else h.upper())]]
             for h in HINTS for lang in LANGS]
    if whole_word_context:
        # Leading delimiter still enables partial credit during search. A right
        # boundary is mandatory to finish; an EOS acts as a virtual delimiter.
        # This refunds CHATGPT credit if its next label extends CHATGPTA.
        paths = [path + [vocab['eng']['|']] for path in paths]
    graph = ContextBias(paths if score else (), score)
    context_tokens = set(t for path in graph.paths for t in path)

    @lru_cache(maxsize=100000)
    def credit(prefix):
        if not prefix:
            return 0., ()
        before, state = credit(prefix[:-1])
        delta, state = graph.step(state, prefix[-1])
        return before + delta, state

    current = {((), lang): (-math.log(2), NEG) for lang in LANGS}
    for frame in range(len(arrays['eng'])):
        check()
        candidates = {lang: set(sorted(by_head[lang], key=lambda t: float(arrays[lang][frame, local[t]]), reverse=True)[:32])
                      | {t for t in context_tokens if language[t] == lang} for lang in LANGS}
        following = {}
        def add(key, pb=NEG, pnb=NEG):
            b, nb = following.get(key, (NEG, NEG))
            following[key] = logadd(b, pb), logadd(nb, pnb)
        for (prefix, active), (pb, pnb) in current.items():
            total = logadd(pb, pnb)
            add((prefix, active), pb=total + float(arrays[active][frame, vocab[active]['<pad>']]))
            last = prefix[-1] if prefix else None
            closed = last in boundaries
            for target in (LANGS if closed else (active,)):
                eligible = candidates[target] | ({last} if last is not None and language[last] == target else set())
                for token in eligible:
                    lp = float(arrays[target][frame, local[token]])
                    if target == active and token == last:
                        # Same CTC frame label does not emit a new token.
                        add((prefix, active), pnb=pnb + lp)
                        if token not in delimiters:
                            add(((*prefix, token), active), pnb=pb + lp)
                        continue
                    if not prefix and token in delimiters:
                        # One leading delimiter is valid and needed for hints.
                        pass
                    elif last in delimiters and token in delimiters:
                        continue
                    if target != active and token in boundaries:
                        continue
                    # Once a word starts choose one of two heads, not one per
                    # acoustic frame. Boundary symbols keep the current head.
                    transition = -math.log(2) if closed and token not in boundaries else 0.
                    add(((*prefix, token), target), pnb=total + transition + lp)
        rank = lambda key: logadd(*following[key]) + credit(key[0])[0]
        current = {key: following[key] for key in sorted(following, key=rank, reverse=True)[:32]}
    results = []
    for (prefix, active), masses in current.items():
        value, state = credit(prefix)
        if whole_word_context and active == 'eng':
            ending, state = graph.step(state, vocab['eng']['|'])
            context = value + ending + graph.finalize(state)
        else:
            context = value + graph.finalize(state)
        acoustic = logadd(*masses)
        if not math.isfinite(acoustic):
            continue
        violations = [i for i in range(1, len(prefix))
                      if language[prefix[i]] != language[prefix[i-1]] and prefix[i-1] not in boundaries]
        if violations or context > score * (len(prefix) + int(whole_word_context)) + 1e-8:
            raise ValueError('Word/head or context-budget violation')
        text = ''.join(tokens[t] for t in prefix).replace('|', ' ').strip()
        results.append({'token_ids': list(prefix), 'raw_text': text, 'postprocessed_text': text,
                        'head_graph_score': acoustic, 'context_credit': context, 'total_score': acoustic + context,
                        'within_word_head_switch_violations': violations,
                        'head_counts': {lang: sum(language[t] == lang for t in prefix) for lang in LANGS}})
    return {'hypotheses': sorted(results, key=lambda h: h['total_score'], reverse=True)[:5],
            'beam': 32, 'score': score, 'whole_word_context': whole_word_context,
            'context_paths': paths if score else [],
            'head_offsets': offsets, 'head_blank_local_ids': {lang: vocab[lang]['<pad>'] for lang in LANGS}}


def main(args):
    import numpy as np
    parent, output, model = Path(args.receipt), Path(args.output), Path(args.model)
    if output.exists():
        raise FileExistsError('Consumed decoder variant')
    before = time.monotonic()
    original = json.loads(parent.read_text())
    downloaded = json.loads((model / 'download-receipt.json').read_text())
    expected = next(row['sha256'] for row in downloaded['files'] if row['name'] == 'vocab.json')
    if digest(model / 'vocab.json') != expected:
        raise ValueError('Changed publisher vocabulary')
    vocab = json.loads((model / 'vocab.json').read_text())
    arrays = {}
    for lang in LANGS:
        path = parent.with_name(parent.stem + '-' + lang + '.npz')
        if digest(path) != original['heads'][lang]['retained_logits_sha256']:
            raise ValueError('Changed head logits')
        with np.load(path) as file:
            arrays[lang] = file['log_probs']
    if arrays['eng'].shape[0] != arrays['rus'].shape[0]:
        raise ValueError('Different head time axes')
    guard = Guard(180, 1536)
    result = {'status': 'failed', 'source_commit': subprocess.check_output(['git', '-C', str(Path(__file__).parent), 'rev-parse', 'HEAD'], text=True).strip(),
              'parent_sha256': digest(parent), 'audio_sha256': original['audio_sha256'],
              'encoder_rerun': False, 'semantic_language_guarantee': False,
              'calibrated_language_detection': False, 'postprocessing': 'none',
              'method': 'head persists within word including blank; choose head at word start'}
    try:
        variants = {}
        for name, score in (('no-context', 0.), ('context', 2.5)):
            variants[name] = search(arrays, vocab, score, guard.check)
            result['variants'] = variants
            save(output.with_name(output.stem + '-' + name + '.json'), variants[name])
            print(name, variants[name]['hypotheses'][0]['raw_text'], flush=True)
        result['status'] = 'success'
    finally:
        result.update(elapsed_s=time.monotonic() - before,
                      peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                      guard=guard.receipt())
        save(output, result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for key in ('receipt', 'output', 'model'):
        parser.add_argument('--' + key, required=True)
    main(parser.parse_args())
