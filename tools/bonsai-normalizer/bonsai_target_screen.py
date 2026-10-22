#!/usr/bin/env python3
"""Once-only round35 target discriminator, not a production editor."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import bonsai_paragraph_screen as base
from bonsai_literal_editor import candidate_spans
from bonsai_normalizer import BonsaiNormalizerConfig
from bonsai_target_editor import BonsaiTargetEditor, TARGET_PROMPT

INPUTS_SHA256 = '459f6237dd9eff78932e5da056a443a06dbcee4ae5882ada76f005dcc5bc9b26'
ORDER = [('story_keep_A', 0, []), ('irritation_delete_A', 1, [0]),
         ('irritation_delete_B', 0, [0]), ('story_keep_B', 1, [])]
MODULE_HASHES = {
    **base.MODULE_HASHES,
    'bonsai_target_editor.py': '8ff796ba5e9de69e046a635c10df6d93894916a7275b3329268a28edd7bbea9e',
    'bonsai_constrained_editor.py': '23d457b417f86e14ae6754b138e74ecd087c163388c28cc3166c8586fc43ba80',
    'bonsai_paragraph_screen.py': 'ab094ce85063e19b99586e7e03840cc2833a6d2b14a317d970a6d01c3a4b9669',
}


def editor_for_cell(cell, token):
    return BonsaiTargetEditor(BonsaiNormalizerConfig(token=token), target=cell['target'])


def validate_inputs(path, expected_hash):
    raw = Path(path).read_bytes()
    if expected_hash != INPUTS_SHA256 or base.digest(raw) != INPUTS_SHA256:
        raise ValueError('Frozen round35 manifest changed')
    cells = base.strict_json(raw)['cells']
    if [(c['id'], c['target'], c['delete']) for c in cells] != ORDER:
        raise ValueError('Frozen round35 cell order/decision changed')
    for c in cells:
        if (len(candidate_spans(c['source'])) != 2
                or editor_for_cell(c, '')._render_candidate(c['source'], json.dumps({'delete': c['delete']})) != c['expected']
                or c['status'] != ('applied' if c['delete'] else 'unchanged')):
            raise ValueError('Frozen round35 scorer changed')
    if cells[0]['source'] != cells[1]['source'] or cells[2]['source'] != cells[3]['source'] or cells[0]['source'] == cells[2]['source']:
        raise ValueError('Frozen round35 source pairing changed')
    return cells


def runtime_hashes():
    root = Path(__file__).resolve().parent
    hashes = {name: base.digest((root/name).read_bytes()) for name in MODULE_HASHES}
    if hashes != MODULE_HASHES:
        raise ValueError('Round35 runtime module drift')
    return {**hashes, 'bonsai_target_screen.py': base.digest(Path(__file__).read_bytes())}


def assess(cell, editor, data, text, meta):
    profile = editor._response_format_for_source(cell['source'])['json_schema']
    canonical = json.dumps(profile['schema'], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    ack = {'name': profile['name'], 'schema_sha256': hashlib.sha256(canonical).hexdigest()}
    if data['bonsai'].get('response_format') != ack:
        raise ValueError('Target schema acknowledgement mismatch')
    content = data['choices'][0]['message']['content']
    try:
        rendered = editor._render_candidate(cell['source'], content)
        valid, ids = True, json.loads(content)['delete']
        copied = rendered == text
    except ValueError:
        valid, ids, copied = False, None, text == cell['source']
    if not copied or meta['reason'] not in (None, 'empty_edit_selection', 'invalid_edit_selection'):
        raise ValueError('Unexpected target client outcome')
    exact, status = text.encode() == cell['expected'].encode(), meta['status'] == cell['status']
    return {'strict_selection_valid': valid, 'actual_selection': ids,
            'exact_copy_verified': copied, 'exact_expected': exact,
            'expected_status': status, 'correct_target_decision': valid and ids == cell['delete'],
            'useful_target_result': exact and status and valid and ids == cell['delete']}


def collect(inputs, inputs_hash, output, token, admission, **kwargs):
    if (admission.get('LFM_loaded_count') != 0 or admission.get('matching_workers') != []
            or admission.get('five_preservation_hashes_match') is not True
            or admission.get('caption_backend') != 'minicpm_q8'):
        raise ValueError('Round35 preservation admission failed')
    return base.collect(inputs, inputs_hash, output, token, admission,
        manifest_validator=validate_inputs, runtime_validator=runtime_hashes,
        cell_editor=editor_for_cell, cell_assessor=assess, prompt_text=TARGET_PROMPT, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--admission')
    parser.add_argument('--admission-sha256')
    args = parser.parse_args()
    cells = validate_inputs(args.inputs, INPUTS_SHA256)
    runtime_hashes()
    if not args.execute:
        print(json.dumps({'validated_cases': [c['id'] for c in cells], 'model_calls': 0}))
        return
    if not args.admission or not args.admission_sha256:
        parser.error('--execute requires fresh hash-pinned Mac admission')
    raw = Path(args.admission).read_bytes()
    if base.digest(raw) != args.admission_sha256:
        raise ValueError('Admission receipt changed')
    result = collect(args.inputs, INPUTS_SHA256, args.output, sys.stdin.read().strip(), base.strict_json(raw))
    print(json.dumps({k: result.get(k) for k in
        ('model_calls', 'completed', 'unknown_outcome', 'http_settled', 'deck_preserved')}))


if __name__ == '__main__':
    main()
