"""Numerical CTC prefix beam on retained full-utterance acoustic logits.

No encoder rerun, text substitution, closed lexicon, or semantic postprocessor.
Beam paths retain CTC blank/nonblank mass and context is applied before pruning.
"""
import argparse
import json
import math
from pathlib import Path
import resource
import subprocess
import time
from functools import lru_cache

from decoder import ContextBias
from run import Guard, context_paths, digest

NEG = float('-inf')


def logadd(a, b):
    if a == NEG: return b
    if b == NEG: return a
    high = max(a, b)
    return high + math.log1p(math.exp(-abs(a - b)))


def search(log_probs, allowed, blank, context, beam, check):
    import numpy as np
    allowed = set(allowed) - {blank}
    context_tokens = set(t for p in context.paths for t in p)
    if not context_tokens.issubset(allowed):
        raise ValueError('Forbidden context token')
    # Each prefix has acoustic (blank, nonblank) masses. Its contextual credit
    # is deterministic and is kept separate, so equivalent alignments log-add.
    @lru_cache(maxsize=100000)
    def bias(prefix):
        if not prefix: return 0.0, ()
        score, state = bias(prefix[:-1])
        delta, state = context.step(state, prefix[-1])
        return score + delta, state

    current = {(): (0.0, NEG)}
    for row in log_probs:
        check()
        top = sorted(allowed, key=lambda t: float(row[t]), reverse=True)[:32]
        eligible = set(top) | context_tokens
        following = {}
        def add(prefix, pb=NEG, pnb=NEG):
            oldb, oldnb = following.get(prefix, (NEG, NEG))
            following[prefix] = logadd(oldb, pb), logadd(oldnb, pnb)
        for prefix, (pb, pnb) in current.items():
            total = logadd(pb, pnb)
            add(prefix, pb=total + float(row[blank]))
            last = prefix[-1] if prefix else None
            # Keeping the prior last token covers repeated frame labels even
            # when it drops out of this frame's acoustic top-k candidates.
            for token in eligible | ({last} if last is not None else set()):
                lp = float(row[token])
                if token == last:
                    add(prefix, pnb=pnb + lp)
                    add((*prefix, token), pnb=pb + lp)
                else:
                    add((*prefix, token), pnb=total + lp)
        rank = lambda p: logadd(*following[p]) + bias(p)[0]
        current = {p: following[p] for p in sorted(following, key=rank, reverse=True)[:beam]}
    results = []
    for prefix, masses in current.items():
        score, state = bias(prefix)
        credit = score + context.finalize(state)
        acoustic = logadd(*masses)
        if not math.isfinite(acoustic): continue
        results.append({'token_ids': list(prefix), 'acoustic_log_prob': acoustic,
                        'context_credit': credit, 'total_score': acoustic + credit})
    return sorted(results, key=lambda h: h['total_score'], reverse=True)[:5]


def equalize_branch_priors(log_probs, artifacts):
    """Remove measured utterance-level language prior, not token acoustics.

    Preserve each frame's RU+EN total mass and blank exactly. This deliberately
    assumes equal prior exposure to the two languages; not estimated truth or a
    semantic-language guarantee. No desired transcript enters the calculation.
    """
    import numpy as np
    lp = np.array(log_probs, dtype=np.float64, copy=True)
    branches = []
    for lang in ('en', 'ru'):
        config = artifacts['languages'][lang]
        branches.append(np.arange(config['offset'], config['offset'] + config['size']))
    if lp.ndim != 2 or lp.shape[1] != artifacts['blank_id'] + 1 or not np.isfinite(lp).all():
        raise ValueError('Invalid retained acoustic logits')
    masses = np.stack([np.exp(lp[:, ids]).sum(axis=1) for ids in branches], axis=1)
    total = masses.sum(axis=1)
    priors = masses.sum(axis=0) / masses.sum()
    if not np.isfinite(priors).all() or np.any(priors <= 0) or np.any(total <= 0):
        raise ValueError('Unmeasurable language prior')
    # Normalize the prior-divided masses back to their original pair mass.
    normalizer = np.log((masses / priors).sum(axis=1)) - np.log(total)
    for k, ids in enumerate(branches):
        lp[:, ids] -= np.log(priors[k]) + normalizer[:, None]
    after = sum(np.exp(lp[:, ids]).sum(axis=1) for ids in branches)
    error = float(np.max(np.abs(after - total)))
    if error > 1e-10 or not np.array_equal(lp[:, artifacts['blank_id']], log_probs[:, artifacts['blank_id']]):
        raise ValueError('Prior correction changed pair mass or blank')
    return lp, {'method': 'utterance-language-prior-division',
                'target_prior': {'en': .5, 'ru': .5},
                'observed_priors': dict(zip(('en', 'ru'), map(float, priors))),
                'maximum_pair_mass_conservation_error': error,
                'blank_unchanged': True, 'within_language_relative_logits_unchanged': True}


def main(args):
    import numpy as np
    output, parent = Path(args.output), Path(args.receipt)
    if output.exists(): raise FileExistsError('Consumed decoding variant')
    original = json.loads(parent.read_text())
    logits_path = parent.with_suffix('.npz')
    if digest(logits_path) != original['retained_logits_sha256']:
        raise ValueError('Retained acoustic probabilities changed')
    guard = Guard(180, 1536)
    started = time.monotonic()
    root = Path(args.root)
    artifacts = json.loads((root / 'prepared/artifacts.json').read_text())
    hints = json.loads((root / 'hints.json').read_text())
    paths, path_receipts = context_paths(root / 'prepared', artifacts, hints)
    for name, expected in artifacts['files_sha256'].items():
        if name in artifacts['tokenizer_models'].values() or name == 'tokens.txt':
            if digest(root / 'prepared' / name) != expected:
                raise ValueError('Prepared tokenizer or token vocabulary changed')
    tokens = {}
    for line in (root / 'prepared/tokens.txt').read_text().splitlines():
        text, i = line.rsplit(' ', 1)
        tokens[int(i)] = text
    result = {'status': 'failed', 'parent_receipt_sha256': digest(parent), 'parameters': vars(args),
              'source_commit': subprocess.check_output(['git', '-C', str(Path(__file__).parent), 'rev-parse', 'HEAD'], text=True).strip(),
              'raw_postprocessing': 'none', 'encoder_rerun': False, 'original_audio_sha256': original['audio_sha256']}
    try:
        with np.load(logits_path) as file:
            lp = file['log_probs']
        result['language_prior_correction'] = None
        if args.equalize_language_priors:
            lp, result['language_prior_correction'] = equalize_branch_priors(lp, artifacts)
        variants = {}
        for name, score in (('no-bias', 0.0), ('context', 2.5)):
            graph = ContextBias(paths if score else (), score)
            hypotheses = search(lp, artifacts['allowed_token_ids'], artifacts['blank_id'], graph, 32, guard.check)
            for h in hypotheses:
                if args.equalize_language_priors:
                    h['prior_adjusted_log_prob'] = h.pop('acoustic_log_prob')
                if any(t not in artifacts['allowed_token_ids'] for t in h['token_ids']):
                    raise ValueError('Forbidden language token emitted')
                h['raw_text'] = ''.join(tokens[t] for t in h['token_ids']).replace('▁', ' ').strip()
                h['postprocessed_text'] = h['raw_text']
                h['en_ids'] = sum(512 <= t < 768 for t in h['token_ids'])
            variants[name] = {'beam': 32, 'score': score, 'context_paths': path_receipts if score else [], 'hypotheses': hypotheses}
        result.update(status='success', variants=variants)
    except Exception as error:
        result['error'] = str(error)
        raise
    finally:
        result.update(elapsed_s=time.monotonic() - started,
                      peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                      guard=guard.receipt())
        with output.open('x') as file:
            json.dump(result, file, ensure_ascii=False, indent=2)
        print(json.dumps({k: v for k, v in result.items() if k != 'variants'}, ensure_ascii=False))
        for name, v in result.get('variants', {}).items():
            print(name, v['hypotheses'][0]['raw_text'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('root', 'receipt', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--equalize-language-priors', action='store_true')
    main(parser.parse_args())
