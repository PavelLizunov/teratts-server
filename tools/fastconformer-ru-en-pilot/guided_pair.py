"""Open trained-head CTC search using only proposal-derived language timing.

The unchanged previously generated Whisper context-rank1 selects a head schedule,
not required output words. No acoustic inference or waveform segmentation.
"""
import argparse
import json
from pathlib import Path
import resource
import subprocess
import time

from mms_pair import LANGS, digest, save
from mms_word_graph import search
from run import Guard


def main(args):
    import numpy as np
    parent, support, output = Path(args.receipt), Path(args.support), Path(args.output)
    if output.exists():
        raise FileExistsError('Consumed guided decoder')
    started = time.monotonic()
    original, evidence = json.loads(parent.read_text()), json.loads(support.read_text())
    if evidence['parent_sha256'] != digest(parent) or evidence['audio_sha256'] != original['audio_sha256']:
        raise ValueError('Wrong proposal support provenance')
    candidates = [r for r in evidence['candidates'] if r['variant'] == 'name-context' and r['original_rank'] == 1]
    if len(candidates) != 1 or candidates[0]['status'] != 'supported':
        raise ValueError('Fixed first proposal cannot supply timing')
    selected = candidates[0]
    arrays, vocab = {}, {}
    for lang in LANGS:
        file = parent.with_name(parent.stem + '-' + lang + '.npz')
        if digest(file) != original['heads'][lang]['retained_logits_sha256']:
            raise ValueError('Retained specialist changed')
        vocab[lang] = original['heads'][lang]['vocab']
        with np.load(file) as data:
            lp = data['log_probs'].astype(np.float64)
        lp[:, [vocab[lang]['<s>'], vocab[lang]['</s>'], vocab[lang]['<unk>']]] = -np.inf
        lp -= np.logaddexp.reduce(lp, axis=1, keepdims=True)
        arrays[lang] = lp
    count = len(arrays['eng'])
    if len(arrays['rus']) != count:
        raise ValueError('Different frame grids')
    sequence = selected['head_label_path']
    schedule = [sequence[0][0]] * count
    for (lang, token), (begin, end) in zip(sequence, selected['label_frame_spans']):
        if not 0 <= begin <= end < count:
            raise ValueError('Invalid guidance span')
        schedule[begin:] = [lang] * (count-begin)
    switches = [{'frame': i, 'center_s': (i * 320 + 199.5) / 16000,
                 'from': schedule[i-1], 'to': schedule[i]}
                for i in range(1, count) if schedule[i] != schedule[i-1]]
    guard = Guard(180, 1536)
    result = {'source_commit': subprocess.check_output(['git', '-C', str(Path(__file__).parent), 'rev-parse', 'HEAD'], text=True).strip(),
              'parent_sha256': digest(parent), 'support_sha256': digest(support), 'audio_sha256': original['audio_sha256'],
              'fixed_proposal_selection': 'Whisper name-context rank1, not reference text',
              'proposal_used_only_for_head_timing': True, 'trained_frame_lid': False,
              'calibrated_language_detection': False, 'head_schedule': schedule, 'switches': switches,
              'encoder_rerun': False, 'waveform_segmentation': False, 'postprocessing': 'none', 'variants': {}}
    for name, score in (('no-context', 0.), ('context', 2.5)):
        before = time.monotonic()
        value = search(arrays, vocab, score, guard.check, hint_case='upper',
                       whole_word_context=True, frame_heads=schedule)
        value['decode_s'] = time.monotonic()-before
        save(output.with_name(output.stem+'-'+name+'.json'), value)
        result['variants'][name] = value
        print(name, value['hypotheses'][0]['raw_text'], flush=True)
    result.update(elapsed_s=time.monotonic()-started, peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                  guard=guard.receipt())
    save(output, result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for key in ('receipt', 'support', 'output'):
        parser.add_argument('--'+key, required=True)
    main(parser.parse_args())
