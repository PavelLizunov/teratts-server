#!/usr/bin/env python3
"""Once-only frozen paragraph screen; dry-run unless --execute, never runs STT."""
import argparse
import base64
import datetime
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
from unittest.mock import patch

from bonsai_normalizer import BonsaiNormalizerConfig, DEFAULT_MODEL, DEFAULT_REVISION
from bonsai_paragraph_structurer import (
    BonsaiParagraphStructurer, PARAGRAPH_PROMPT, paragraph_boundaries, render_paragraphs,
)

INPUTS_SHA256 = '57fab275f08d3c505a09c2542f94dbe0baef089b704af4a20d8369027c0586f4'
SERVICE_SHA256 = '35472797d745bfce5f5726122dd6361f49b17f21ee51ead8aa5df42933f858f0'
SOURCE_COMMIT = 'c05ebac2df0e03b6473b1242dcffdec01056e521'
GATEWAY_SHA256 = '0fee7132c77769bff880607a0f41afe4ab308230ed4c5cd3d229c11ecf05f6c1'
MODULE_HASHES = {
    'bonsai_normalizer.py': '809aac74b11e3a68aa635c945c0d128ac0c5d2b84122aa18f56fa1f58bb6a092',
    'bonsai_literal_editor.py': '803dceef9d7ca68b2869106cc43014408b90aafa76405d6c9d5cb7fa839afe14',
    'bonsai_paragraph_structurer.py': '5edd9e33524cba67e343157b4ba8edd31bb9087c94ab44760ee068f3a66266aa',
}
CELL_IDS = ('two_topical_blocks', 'condition_action_block_then_travel',
            'single_topic_requires_abstention', 'mixed_language_preservation_and_meeting')
HEALTH = {'status': 'ok', 'model': DEFAULT_MODEL, 'revision': DEFAULT_REVISION, 'loaded': False}
BASE = 'http://127.0.0.1:18091'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def validate_inputs(path, expected_hash):
    raw = Path(path).read_bytes()
    if expected_hash != INPUTS_SHA256 or digest(raw) != INPUTS_SHA256:
        raise ValueError('Frozen input manifest changed')
    cells = json.loads(raw)['cells']
    if [c['id'] for c in cells] != list(CELL_IDS):
        raise ValueError('Frozen case order changed')
    for cell in cells:
        if (len(paragraph_boundaries(cell['source'])) != 3
                or render_paragraphs(cell['source'], json.dumps({'break_after': cell['break_after']}))
                != cell['expected']
                or cell['status'] != ('applied' if cell['break_after'] else 'unchanged')):
            raise ValueError('Frozen scorer/plan mismatch')
    return cells


def runtime_hashes():
    root = Path(__file__).resolve().parent
    hashes = {name: digest((root / name).read_bytes()) for name in MODULE_HASHES}
    if hashes != MODULE_HASHES:
        raise ValueError('Frozen runtime module drift')
    return hashes


def strict_json(raw):
    def reject_constant(_):
        raise ValueError('Nonfinite JSON response')
    def finite_float(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError('Nonfinite JSON response')
        return value
    return json.loads(raw, parse_constant=reject_constant, parse_float=finite_float)


def finite(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('Invalid resource observation')
    return value


def validate_admission(observation, now):
    timestamp = datetime.datetime.fromisoformat(observation['at'])
    if timestamp.tzinfo is None or not 0 <= now - timestamp.timestamp() <= 60:
        raise ValueError('Stale or future Mac admission observation')
    if (observation['source_commit'] != SOURCE_COMMIT
            or observation['source_service_sha256'] != SERVICE_SHA256
            or observation['copied_service_sha256'] != SERVICE_SHA256
            or observation['health'] != HEALTH or observation['vision_lock_free'] is not True
            or finite(observation['memory']['available_GiB']) < 5.5):
        raise ValueError('Paragraph admission failed')
    finite(observation['memory']['swap_GiB'])


def observe_deck():
    gateway = Path('/home/deck/homelab/gateway/server.py')
    services = subprocess.check_output(['systemctl', '--user', 'is-active',
        'voice-gateway.service', 'parakeet-stt.service', 'loqira-corrector.service',
        'bonsai9-mac-tunnel.service'], text=True, timeout=10).splitlines()
    state = {'gateway_sha256': digest(gateway.read_bytes()), 'services': services}
    if state != {'gateway_sha256': GATEWAY_SHA256, 'services': ['active'] * 4}:
        raise ValueError('Accepted Deck runtime drift')
    return state


def collect(inputs, inputs_hash, output, token, admission, *, opener=None,
            clock=time.monotonic, wall_clock=time.time, deck_observer=observe_deck,
            manifest_validator=validate_inputs, runtime_validator=runtime_hashes,
            cell_editor=None, cell_assessor=None, prompt_text=PARAGRAPH_PROMPT):
    """No retry; unknown submission/body-read skips unload and further calls.

    Mac admission is a fresh coordinator observation, not an automated headroom
    poll. HTTP settlement does not prove a new Mac vision-lock observation.
    """
    cells = manifest_validator(inputs, inputs_hash)
    hashes = runtime_validator()
    if len(token.strip()) < 32:
        raise ValueError('Invalid token')
    output = Path(output)
    validate_admission(admission, wall_clock())
    result = {'inputs_sha256': inputs_hash, 'module_sha256': hashes,
              'collector_sha256': digest(Path(__file__).read_bytes()),
              'prompt_sha256': digest(prompt_text.encode()), 'admission': admission,
              'model_calls': 0, 'telegram_calls': 0, 'completed': False,
              'unknown_outcome': False, 'rows': []}
    with output.open('x') as handle:
        output.chmod(0o600)
        json.dump(result, handle, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())

    def save():
        # Encode before truncating: an invalid parsed value must not destroy
        # the already-fsynced raw response or submission intent.
        encoded = json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False)
        with output.open('w') as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())

    editor = BonsaiParagraphStructurer(BonsaiNormalizerConfig(token=token.strip()))
    real_open = (opener or editor._opener).open
    headers = {'Authorization': 'Bearer ' + token.strip(), 'Content-Type': 'application/json'}

    def control(path, data=None):
        request = urllib.request.Request(BASE + path, headers=headers,
            data=None if data is None else json.dumps(data).encode())
        with real_open(request, timeout=115) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError('Oversized control response')
        return strict_json(raw)

    total_start = clock()
    start = None
    try:
        result['deck_before'] = deck_observer()
        result['before'] = control('/health')
        if result['before'] != HEALTH:
            raise ValueError('Unexpected current health/identity or already loaded')
        # Time spent on control requests cannot make an old admission fresh.
        validate_admission(admission, wall_clock())
        start = clock()
        for cell in cells:
            if cell_editor is not None:
                editor = cell_editor(cell, token.strip())
            if clock() - start >= 600:
                raise TimeoutError('Screen budget exhausted before case')
            active = dict(cell, outcome='not_submitted')
            result['rows'].append(active)
            save()

            def capture(request, *, timeout):
                expected = {'model': DEFAULT_MODEL,
                    'messages': editor._messages_for_source(cell['source']),
                    'temperature': 0.0, 'top_p': 0.8, 'top_k': 20, 'min_p': 0.0,
                    'presence_penalty': 0.0, 'repetition_penalty': 1.0,
                    'seed': 42, 'max_tokens': 1024, 'stream': False}
                response_format = editor._response_format_for_source(cell['source'])
                if response_format is not None:
                    expected['response_format'] = response_format
                if (active['outcome'] != 'not_submitted' or request.full_url != BASE + '/v1/chat/completions'
                        or json.loads(request.data) != expected):
                    raise ValueError('Paragraph payload drift or duplicate submission')
                remaining = 600 - (clock() - start)
                if remaining <= 0:
                    raise TimeoutError('Screen budget exhausted before submission')
                active.update(payload_sha256=digest(request.data), outcome='submitted_unknown',
                    submitted_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
                result['model_calls'] += 1
                result['unknown_outcome'] = True
                save()
                try:
                    try:
                        response = real_open(request, timeout=min(timeout, remaining))
                    except urllib.error.HTTPError as error:
                        response = error
                    with response:
                        raw = response.read(65537)
                        status = getattr(response, 'status', 200)
                    active.update(outcome='response_received', http_status=status,
                        raw_base64=base64.b64encode(raw).decode(), response_sha256=digest(raw))
                    result['unknown_outcome'] = False
                    save()
                except BaseException as error:
                    active['transport_error_type'] = type(error).__name__
                    save()
                    raise
                return io.BytesIO(raw)

            begun = clock()
            with patch.object(editor._opener, 'open', capture):
                text, meta = editor.normalize(cell['source'])
            active.update(returned=text, metadata=meta, seconds=clock() - begun)
            save()
            if result['unknown_outcome']:
                raise RuntimeError('Unresolved paragraph submission; observe, never replay or unload')
            if active['outcome'] != 'response_received':
                raise ValueError('Paragraph request was not submitted')
            if active['http_status'] != 200:
                raise ValueError('Known paragraph HTTP rejection')
            raw = base64.b64decode(active['raw_base64'])
            if len(raw) > 65536:
                raise ValueError('Oversized paragraph response')
            data = active['response'] = strict_json(raw)
            bm = data['bonsai']
            choice = data['choices'][0]
            if (data['model'] != DEFAULT_MODEL or bm['revision'] != DEFAULT_REVISION
                    or bm['thinking'] is not False or bm['profile'] != 'baseline'
                    or choice['finish_reason'] != 'stop' or not isinstance(choice['message']['content'], str)):
                raise ValueError('Paragraph identity/profile/finish drift')
            if (finite(bm['memory_end']['available_GiB']) < 2.0
                    or finite(bm['memory_end']['swap_GiB']) - admission['memory']['swap_GiB'] > 0.25):
                raise MemoryError('Paragraph resource stop')
            active['protocol_validated'] = True
            if cell_assessor is not None:
                active.update(cell_assessor(cell, editor, data, text, meta))
            else:
                try:
                    content = choice['message']['content']
                    rendered = render_paragraphs(cell['source'], content)
                    active.update(strict_selection_valid=True, actual_selection=json.loads(content)['break_after'],
                                  insertion_plan_verified=(rendered == text))
                except ValueError:
                    active.update(strict_selection_valid=False, insertion_plan_verified=(text == cell['source']))
                active.update(exact_expected=(text.encode() == cell['expected'].encode()),
                              expected_status=(meta['status'] == cell['status']))
                active['useful_grouping'] = active['exact_expected'] and active['expected_status']
                if (not active['insertion_plan_verified']
                        or meta['reason'] not in (None, 'empty_paragraph_selection', 'invalid_edit_selection')):
                    raise ValueError('Unexpected paragraph client outcome')
            save()
            if clock() - start >= 600:
                raise TimeoutError('Screen budget exhausted after response')
        result['completed'] = True
    except BaseException as error:
        result['stopped_error_type'] = type(error).__name__
        raise
    finally:
        primary_error = 'stopped_error_type' in result
        result['screen_elapsed_seconds'] = None if start is None else clock() - start
        result['collection_elapsed_before_settlement_seconds'] = clock() - total_start
        save_error = None
        try:
            save()
        except Exception as error:
            result['primary_save_error_type'] = type(error).__name__
            save_error = error
        if result['model_calls'] and not result['unknown_outcome']:
            try:
                result['unload'] = control('/unload', {})
                result['after'] = control('/health')
                result['http_settled'] = result['unload'] == {'unloaded': True} and result['after'] == HEALTH
            except Exception as error:
                result['settlement_error_type'] = type(error).__name__
            try:
                result['deck_after'] = deck_observer()
                result['deck_preserved'] = result['deck_after'] == result['deck_before']
            except Exception as error:
                result['deck_observation_error_type'] = type(error).__name__
            result['Mac_final_lock_verification'] = 'required separately; initial admission is not final settlement'
        result['total_collection_seconds'] = clock() - total_start
        try:
            save()
        except Exception as error:
            if save_error is None:
                save_error = error
        if save_error is not None and not primary_error:
            raise save_error
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', required=True)
    parser.add_argument('--inputs-sha256', default=INPUTS_SHA256)
    parser.add_argument('--output', required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--admission')
    parser.add_argument('--admission-sha256')
    args = parser.parse_args()
    if args.inputs_sha256 != INPUTS_SHA256:
        parser.error('Use the frozen round-9 input manifest hash')
    if not args.execute:
        cells = validate_inputs(args.inputs, args.inputs_sha256)
        runtime_hashes()
        print(json.dumps({'validated_cases': [c['id'] for c in cells], 'model_calls': 0}))
        return
    if not args.admission or not args.admission_sha256:
        parser.error('--execute requires a fresh hash-pinned Mac admission receipt')
    raw = Path(args.admission).read_bytes()
    if digest(raw) != args.admission_sha256:
        raise ValueError('Admission receipt changed')
    result = collect(args.inputs, args.inputs_sha256, args.output, sys.stdin.read().strip(), json.loads(raw))
    print(json.dumps({k: result.get(k) for k in
        ('model_calls', 'completed', 'unknown_outcome', 'http_settled', 'deck_preserved')}))


if __name__ == '__main__':
    main()
