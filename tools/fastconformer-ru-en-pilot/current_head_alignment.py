"""Auxiliary alignment on current native heads, followed by open CTC decoding.

The fixed saved proposal constrains only alignment. Its words are not supplied
to the final open search. Both acoustic arrays retain their original time grids.
"""
import argparse
import json
import math
from pathlib import Path
import resource
import subprocess
import time

from mms_pair import HINTS, digest, save
from native_clock_pair import decode
from proposal_support import labels
from run import Guard


def align(events, sequence, blank, delimiter, check):
    import numpy as np
    states = [{'head': sequence[0][0], 'token': blank[sequence[0][0]],
               'label': None, 'kind': 'initial_blank', 'predecessors': []}]
    last_label, last_blank = None, 0
    for index, (lang, token) in enumerate(sequence):
        predecessors = [last_blank]
        if last_label is not None:
            old_lang, old_token = sequence[index-1]
            if (lang, token) != (old_lang, old_token):
                predecessors.append(last_label)
            if lang != old_lang:
                if old_token != delimiter[old_lang]:
                    raise ValueError('Auxiliary head switch inside a word')
                states.append({'head': lang, 'token': blank[lang], 'label': None,
                               'kind': 'entry_blank', 'predecessors': [last_label, last_blank]})
                predecessors.append(len(states)-1)
        states.append({'head': lang, 'token': token, 'label': index,
                       'kind': 'label', 'predecessors': predecessors})
        last_label = len(states)-1
        states.append({'head': lang, 'token': blank[lang], 'label': None,
                       'kind': 'blank_after', 'predecessors': [last_label]})
        last_blank = len(states)-1
    count = len(states)
    best = np.full(count, -np.inf)
    best[0] = 0.
    parents = np.empty((len(events), count), np.int32)
    for frame, event in enumerate(events):
        check()
        following = best.copy()
        parents[frame] = np.arange(count)
        factor = 2. if event['head'] == 'rus' else 1.
        for state_id, state in enumerate(states):
            if state['head'] != event['head']:
                continue  # Inactive native head is neither repeated nor scored.
            candidates = [state_id, *state['predecessors']]
            source = max(candidates, key=lambda k: best[k])
            following[state_id] = best[source] + factor*float(event['log_probs'][state['token']])
            parents[frame, state_id] = source
        best = following
    terminal = max((last_label, last_blank), key=lambda k: best[k])
    score = float(best[terminal])
    if not math.isfinite(score):
        raise ValueError('No complete finite current-head alignment')
    selected, trace = [], []
    label_frames = [[] for _ in sequence]
    checked_score, state_id = 0., terminal
    for frame in range(len(events)-1, -1, -1):
        event, state = events[frame], states[state_id]
        source = int(parents[frame, state_id])
        if state['head'] == event['head']:
            selected.append(event)
            weighted = (2. if event['head'] == 'rus' else 1.)*float(event['log_probs'][state['token']])
            checked_score += weighted
            trace.append({'union_event': frame, 'head': event['head'], 'native_frame': event['native_frame'],
                          'center_s': event['center_s'], 'local_token': state['token'], 'kind': state['kind'],
                          'label': state['label'], 'state': state_id, 'source_state': source,
                          'weighted_log_probability': weighted})
            if state['label'] is not None:
                label_frames[state['label']].append(frame)
        elif source != state_id:
            raise ValueError('Inactive event advanced the alignment')
        state_id = source
    if state_id != 0 or any(not frames for frames in label_frames):
        raise ValueError('Incomplete proposal coverage')
    if abs(score-checked_score) > 1e-7:
        raise ValueError('Backtrace and alignment score disagree')
    selected.reverse()
    trace.reverse()
    for i, event in enumerate(selected):
        event['index'] = i
    switches = []
    for i in range(1, len(trace)):
        old, new = trace[i-1], trace[i]
        if old['head'] != new['head']:
            source_state = states[new['source_state']]
            if source_state['head'] != old['head']:
                raise ValueError('Unaccounted head switch')
            switches.append({'from': old['head'], 'to': new['head'],
                             'old_last_center_s': old['center_s'], 'new_first_center_s': new['center_s'],
                             'new_kind': new['kind'], 'source_state': new['source_state'], 'state': new['state']})
    return selected, {'objective': 'duration-weighted composite Viterbi, not calibrated probability',
                      'stride_weights': {'rus': 2., 'eng': 1.}, 'score': score,
                      'backtrace_score_error': abs(score-checked_score), 'states': states,
                      'selected_events': trace, 'ignored_inactive_events': len(events)-len(selected),
                      'label_union_event_spans': [[min(x), max(x)] for x in label_frames], 'switches': switches}


def main(args):
    import numpy as np
    rp, ep, pp, output = map(Path, (args.russian, args.english, args.proposals, args.output))
    alignment_path = output.with_name(output.stem+'-alignment.json')
    if output.exists() or alignment_path.exists():
        raise FileExistsError('Consumed or unknown alignment attempt')
    started = time.monotonic()
    guard = Guard(180, 1536)
    result = {'status': 'failed', 'variants': {}, 'audio_or_encoder_rerun': False,
              'probability_interpolation': False, 'per_region_decoders': False,
              'proposal_text_used_by_final_decoder': False, 'postprocessing': 'none',
              'source_commit': subprocess.check_output(['git', '-C', str(Path(__file__).parent), 'rev-parse', 'HEAD'], text=True).strip()}
    try:
        ru, en, proposal = (json.loads(p.read_text()) for p in (rp, ep, pp))
        if len({ru['audio_sha256'], en['audio_sha256'], proposal['audio_sha256']}) != 1:
            raise ValueError('Mixed original recordings')
        en_file = ep.with_name(ep.stem+'-eng.npz')
        if digest(rp.with_suffix('.npz')) != ru['retained_logits_sha256'] or digest(en_file) != en['heads']['eng']['retained_logits_sha256']:
            raise ValueError('Changed native acoustic evidence')
        token_file = Path(args.russian_model)/'tokens.txt'
        asset_file = token_file.parent/'download-receipt.json'
        assets = json.loads(asset_file.read_text())
        if digest(asset_file) != ru['asset_receipt_sha256'] or digest(token_file) != next(r['sha256'] for r in assets['files'] if r['name']=='tokens.txt'):
            raise ValueError('Changed Russian trained vocabulary')
        rtokens = {int(line.rsplit(' ', 1)[1]): line.rsplit(' ', 1)[0] for line in token_file.read_text().splitlines()}
        if len(rtokens) != 34 or rtokens[0] != ' ' or rtokens[33] != '<blk>':
            raise ValueError('Unexpected Russian head')
        vocab = {'eng': en['heads']['eng']['vocab'], 'rus': {v:k for k,v in rtokens.items() if k != 33}}
        vocab['rus']['|'] = vocab['rus'].pop(' ')
        raw_proposal = proposal['variants']['name-context']['hypotheses'][0]['raw_text']
        sequence, scoring_text, words = labels(raw_proposal, vocab)
        with np.load(rp.with_suffix('.npz')) as file: rlp = file['log_probs'].astype(np.float64)
        with np.load(en_file) as file: elp = file['log_probs'].astype(np.float64)
        elp[:, [vocab['eng']['<s>'], vocab['eng']['</s>'], vocab['eng']['<unk>']]] = -np.inf
        elp -= np.logaddexp.reduce(elp, axis=1, keepdims=True)
        events = []
        for lang, array, stride, origin in (('eng', elp, 320, 199.5), ('rus', rlp, 640, 159.5)):
            for index, row in enumerate(array):
                events.append({'head': lang, 'native_frame': index, 'center_s': (index*stride+origin)/16000,
                               'log_probs': row})
        events.sort(key=lambda event: event['center_s'])
        selected, alignment = align(events, sequence, {'eng': 0, 'rus': 33}, {'eng': 4, 'rus': 0}, guard.check)
        result.update(audio_sha256=ru['audio_sha256'], russian_receipt_sha256=digest(rp), english_receipt_sha256=digest(ep),
                      proposals_sha256=digest(pp), fixed_proposal_selection='name-context rank1',
                      native_rows={lang: sum(e['head']==lang for e in selected) for lang in vocab})
        alignment.update(raw_auxiliary_proposal=raw_proposal, lexical_scoring_text=scoring_text,
                         proposal_words=words, label_path=sequence, **{k:v for k,v in result.items() if k not in ('status','variants')})
        save(alignment_path, alignment)
        result.update(alignment_sha256=digest(alignment_path), alignment_s=time.monotonic()-started)
        tokens = {i: (' ' if p=='|' else p) for p,i in vocab['eng'].items() if p not in ('<pad>','<s>','</s>','<unk>')}
        tokens.update({32+i:p for i,p in rtokens.items() if i!=33})
        heads = {'eng': {i:i for i in tokens if i<32}, 'rus': {32+i:i for i in rtokens if i!=33}}
        paths = [[space, *[vocab['eng']['|' if c==' ' else c] for c in hint.upper()], 4]
                 for hint in HINTS for space in (4, 32)]
        for name, score in (('no-context', 0.), ('context', 2.5)):
            before = time.monotonic()
            value = decode(selected, tokens, heads, {4, 32}, {'eng': 0, 'rus': 33}, paths, score, guard.check)
            if not value['hypotheses']:
                raise ValueError('Empty finite open-beam output')
            for hypothesis in value['hypotheses']:
                active = None
                for token in hypothesis['token_ids']:
                    if token not in tokens:
                        raise ValueError('Forbidden trained-head output')
                    if token in (4, 32): active = None; continue
                    lang = 'eng' if token<32 else 'rus'
                    if active and active != lang:
                        raise ValueError('Within-word head change')
                    active = lang
            value['decode_s'] = time.monotonic()-before
            save(output.with_name(output.stem+'-'+name+'.json'), value)
            result['variants'][name] = value
            print(name, value['hypotheses'][0]['raw_text'], flush=True)
        result['status'] = 'success'
    except Exception as error:
        result['error'] = type(error).__name__+': '+str(error)
        raise
    finally:
        result.update(elapsed_s=time.monotonic()-started, peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                      guard=guard.receipt())
        save(output, result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for key in ('russian', 'english', 'proposals', 'russian-model', 'output'):
        parser.add_argument('--'+key, required=True)
    main(parser.parse_args())
