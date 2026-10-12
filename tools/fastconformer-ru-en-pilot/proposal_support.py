"""Exact retained pair-CTC support for existing whole-recording N-best proposals.

DIAGNOSTIC ONLY: finite candidates are not an open-vocabulary recognizer and
lexical head representability is not semantic RU/EN restriction of Whisper.
No proposed string is repaired, generated, or silently dropped.
"""
import argparse
import json
import math
from pathlib import Path
import subprocess
import time
import unicodedata

from mms_pair import LANGS, digest, save


def labels(text, vocab):
    words, pending = [], ''
    for char in text:
        if char.isspace() or unicodedata.category(char)[0] in 'PZS' and char != "'":
            if pending:
                words.append(pending)
                pending = ''
        else:
            pending += char
    if pending:
        words.append(pending)
    result, normalized, provenance = [], [], []
    previous = None
    for word in words:
        matches = []
        for lang in LANGS:
            transformed = word.upper() if lang == 'eng' else word.lower()
            if transformed and all(c in vocab[lang] and len(c) == 1 for c in transformed):
                matches.append((lang, transformed))
        if len(matches) != 1:
            raise ValueError('Word not uniquely represented by a trained head: ' + word)
        lang, transformed = matches[0]
        if previous:
            result.append((previous, vocab[previous]['|']))
        begin = len(result)
        result.extend((lang, vocab[lang][c]) for c in transformed)
        provenance.append({'original_word': word, 'scored_word': transformed, 'head': lang,
                           'first_label': begin, 'last_label': len(result)-1})
        normalized.append(transformed)
        previous = lang
    if not result:
        raise ValueError('Empty proposal')
    return result, ' '.join(normalized), provenance


def support(arrays, sequence, vocab):
    import numpy as np
    frames, count = len(arrays['eng']), 2 * len(sequence) + 1
    emissions = np.empty((frames, count), dtype=np.float64)
    transition = np.zeros(count, dtype=np.float64)
    skip = np.zeros(count, dtype=bool)
    for state in range(count):
        if state % 2:
            index = state // 2
            lang, token = sequence[index]
            emissions[:, state] = arrays[lang][:, token]
            if index:
                before_lang, before_token = sequence[index-1]
                if before_token == vocab[before_lang]['|'] and token != vocab[lang]['|']:
                    transition[state] = -math.log(2)
                skip[state] = sequence[index] != sequence[index-1]
        else:
            lang = sequence[max(0, state//2-1)][0]
            emissions[:, state] = arrays[lang][:, vocab[lang]['<pad>']]
    summed = np.full(count, -np.inf)
    summed[0] = -math.log(2)
    best = summed.copy()
    parents = np.zeros((frames, count), dtype=np.int8)
    for frame in range(frames):
        stay, advance, jump = best, np.full(count, -np.inf), np.full(count, -np.inf)
        advance[1:] = best[:-1] + transition[1:]
        jump[2:] = np.where(skip[2:], best[:-2] + transition[2:], -np.inf)
        choices = np.stack((stay, advance, jump))
        parents[frame] = choices.argmax(0)
        best = choices.max(0) + emissions[frame]
        advance[1:] = summed[:-1] + transition[1:]
        jump[2:] = np.where(skip[2:], summed[:-2] + transition[2:], -np.inf)
        summed = np.logaddexp(np.logaddexp(summed, advance), jump) + emissions[frame]
    score = float(np.logaddexp(summed[-1], summed[-2]))
    end = count-1 if best[-1] >= best[-2] else count-2
    viterbi_score = float(best[end])
    if not math.isfinite(score) or not math.isfinite(viterbi_score):
        raise ValueError('No complete finite acoustic alignment')
    label_frames = [[] for _ in sequence]
    for frame in range(frames-1, -1, -1):
        if end % 2:
            label_frames[end//2].append(frame)
        end -= int(parents[frame, end])
    if end != 0 or any(not x for x in label_frames):
        raise ValueError('Invalid complete alignment provenance')
    return {'head_graph_logsum': score, 'viterbi_log_prob': viterbi_score,
            'label_frame_spans': [[min(x), max(x)] for x in label_frames]}


def main(args):
    import numpy as np
    output, parent, proposals = Path(args.output), Path(args.receipt), Path(args.proposals)
    if output.exists():
        raise FileExistsError('Consumed proposal-support diagnostic')
    started = time.monotonic()
    original, saved = json.loads(parent.read_text()), json.loads(proposals.read_text())
    if original['audio_sha256'] != saved['audio_sha256']:
        raise ValueError('Different original audio')
    arrays, vocab = {}, {}
    for lang in LANGS:
        file = parent.with_name(parent.stem + '-' + lang + '.npz')
        if digest(file) != original['heads'][lang]['retained_logits_sha256']:
            raise ValueError('Retained head changed')
        vocab[lang] = original['heads'][lang]['vocab']
        with np.load(file) as data:
            lp = data['log_probs'].astype(np.float64)
        lp[:, [vocab[lang]['<s>'], vocab[lang]['</s>'], vocab[lang]['<unk>']]] = -np.inf
        lp -= np.logaddexp.reduce(lp, axis=1, keepdims=True)
        arrays[lang] = lp
    if len(arrays['eng']) != len(arrays['rus']):
        raise ValueError('Head frame grids differ')
    results = []
    for variant, values in saved['variants'].items():
        for rank, hypothesis in enumerate(values['hypotheses']):
            row = {'variant': variant, 'original_rank': rank+1, 'raw_text': hypothesis['raw_text'],
                   'whisper_score_not_used': hypothesis['score']}
            try:
                sequence, normalized, words = labels(row['raw_text'], vocab)
                row.update(support(arrays, sequence, vocab), lexical_scoring_text=normalized,
                           head_label_path=sequence, word_provenance=words, status='supported')
            except ValueError as error:
                row.update(status='unsupported', reason=str(error))
            results.append(row)
    result = {'diagnostic_only': True, 'open_vocabulary_decoder': False, 'whisper_hard_pair_constraint': False,
              'new_transcript': False, 'audio_or_encoder_rerun': False, 'parent_sha256': digest(parent),
              'proposals_sha256': digest(proposals), 'audio_sha256': original['audio_sha256'],
              'source_commit': subprocess.check_output(['git', '-C', str(Path(__file__).parent), 'rev-parse', 'HEAD'], text=True).strip(),
              'candidates': results, 'elapsed_s': time.monotonic()-started}
    save(output, result)
    for row in sorted(results, key=lambda r:r.get('head_graph_logsum', -math.inf), reverse=True):
        print(row['variant'], row['original_rank'], row.get('head_graph_logsum'), row['raw_text'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for key in ('receipt', 'proposals', 'output'):
        parser.add_argument('--'+key, required=True)
    main(parser.parse_args())
