#!/usr/bin/env python3
"""Four once-only round31 cells, reusing durable paragraph collection unchanged."""
import argparse
import json
from pathlib import Path
import sys

import bonsai_paragraph_screen as base
from bonsai_context_paragraph import BonsaiContextParagraphStructurer
from bonsai_normalizer import BonsaiNormalizerConfig
from bonsai_paragraph_structurer import BonsaiParagraphStructurer, paragraph_boundaries, render_paragraphs

INPUTS_SHA256 = '8e474bd496ff2a42f36612fee7eb0df08517a1fb369a9f0db3f45eab05067ec9'
ORDER = [('topic_offsets', 'offsets'), ('topic_context', 'context'),
         ('condition_context', 'context'), ('condition_offsets', 'offsets')]
MODULE_HASHES = {
    **base.MODULE_HASHES,
    'bonsai_context_paragraph.py': 'e612df6d4efbd1e4359651ca5b6781bd2d3a5c1f39a316eca6a78c0a4daac281',
    'bonsai_paragraph_screen.py': '18934ea25af8542e63cd1bd8fcb094627dbd051f93fb5237dc7e78b8a0922d8c',
}


def validate_inputs(path, expected_hash):
    raw = Path(path).read_bytes()
    if expected_hash != INPUTS_SHA256 or base.digest(raw) != INPUTS_SHA256:
        raise ValueError('Frozen round31 manifest changed')
    cells = base.strict_json(raw)['cells']
    if [(c['id'], c['representation']) for c in cells] != ORDER:
        raise ValueError('Frozen round31 cell order changed')
    for i, cell in enumerate(cells):
        expected_ids = [1] if i < 2 else []
        if (cell['break_after'] != expected_ids
                or len(paragraph_boundaries(cell['source'])) != 3
                or render_paragraphs(cell['source'], json.dumps({'break_after': expected_ids})) != cell['expected']
                or cell['status'] != ('applied' if expected_ids else 'unchanged')):
            raise ValueError('Frozen round31 scorer changed')
    for a, b in (cells[:2], cells[2:]):
        if any(a[key] != b[key] for key in ('source', 'break_after', 'expected', 'status')):
            raise ValueError('Paired source/scorer drift')
    return cells


def runtime_hashes():
    root = Path(__file__).resolve().parent
    hashes = {name: base.digest((root/name).read_bytes()) for name in MODULE_HASHES}
    if hashes != MODULE_HASHES:
        raise ValueError('Round31 runtime module drift')
    return {**hashes, 'bonsai_context_paragraph_screen.py': base.digest(Path(__file__).read_bytes())}


def editor_for_cell(cell, token):
    kind = {'offsets': BonsaiParagraphStructurer, 'context': BonsaiContextParagraphStructurer}[cell['representation']]
    return kind(BonsaiNormalizerConfig(token=token))


def collect(inputs, inputs_hash, output, token, admission, **kwargs):
    if (admission.get('LFM_loaded_count') != 0 or admission.get('matching_workers') != []
            or admission.get('five_preservation_hashes_match') is not True
            or admission.get('caption_backend') != 'minicpm_q8'):
        raise ValueError('Round31 preservation admission failed')
    return base.collect(inputs, inputs_hash, output, token, admission,
        manifest_validator=validate_inputs, runtime_validator=runtime_hashes,
        cell_editor=editor_for_cell, **kwargs)


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
        parser.error('--execute requires a fresh hash-pinned Mac admission')
    raw = Path(args.admission).read_bytes()
    if base.digest(raw) != args.admission_sha256:
        raise ValueError('Admission receipt changed')
    result = collect(args.inputs, INPUTS_SHA256, args.output, sys.stdin.read().strip(), base.strict_json(raw))
    print(json.dumps({k: result.get(k) for k in
        ('model_calls', 'completed', 'unknown_outcome', 'http_settled', 'deck_preserved')}))


if __name__ == '__main__':
    main()
