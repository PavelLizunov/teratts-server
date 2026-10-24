#!/usr/bin/env python3
"""Once-only rewrite checks through installed gateway on a private live HTTP socket.

ASR and Loqira are synthetic stubs. Dictionary, routing, Bolt client/HTTP/service
and response serialization are real installed code. Never replay a consumed case.
The frozen rubric is a bounded quality screen, not semantic-equivalence proof.
"""
import argparse
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sys
import threading
import time
from unittest.mock import patch

import bolt_gateway_acceptance as receipts


def score(text, case):
    """Evaluate pre-frozen fact patterns, neutral language and paragraph requirement."""
    checks = {label: bool(re.search(pattern, text, re.I | re.S))
              for label, pattern in case['required_patterns'].items()}
    checks['no_profanity'] = not re.search(case['forbidden_pattern'], text, re.I)
    if case.get('paragraphs'):
        checks['paragraphs'] = bool(re.search(r'\n\s*\n', text))
    return {'checks': checks, 'rubric_passed': all(checks.values()),
            'manual_semantic_review_required': True}


async def execute(args, case, root):
    import uvicorn
    homelab = Path.home() / 'homelab'
    installed = homelab / 'gateway/server.py'
    receipts.need(hashlib.sha256(installed.read_bytes()).hexdigest() == args.gateway_sha256,
                  'Installed gateway drift')
    os.environ['BONSAI_ASGI_TEST'] = '1'
    os.environ['BONSAI_GATEWAY_TEST_SOURCE'] = str(installed)
    tests = Path(__file__).parent / 'tests/test_gateway_asgi.py'
    harness = receipts.module('bolt_rewrite_live_harness', tests)
    fixture = harness.TestFullGatewayASGI('test_real_multipart_precedence_provenance_and_formats')
    fixture.editor_startup_env = {
        'BOLT_NORMALIZER_CONFIG': str(homelab / 'config/bolt-normalizer.json'),
        'STT_DICTIONARY_CONFIG': str(homelab / 'config/stt-dictionary.json')}
    fixture.installed_gateway_dir = homelab / 'gateway'
    server = thread = listener = None
    calls = []
    try:
        fixture.setUp()
        fixture.network.stop()
        gateway = fixture.gateway
        gateway.run_parakeet = lambda _: case['source']
        gateway.loqira_corrector = lambda text: (text, {
            'status': 'applied', 'loqira_ms': 0.0, 'sage_ms': 0.0})
        normalizer = gateway.bonsai_normalizer
        receipts.need(normalizer is not None and type(normalizer).__name__ == 'BoltNormalizer'
                      and type(normalizer).__module__ == 'gateway.bolt_normalizer',
                      'Installed startup did not select Bolt')
        receipts.need(Path(sys.modules['gateway.bolt_normalizer'].__file__).resolve()
                      == (homelab / 'gateway/bolt_normalizer.py').resolve(), 'Client source drift')
        transport = normalizer._opener
        real_open = transport.open

        def capture(request, *positional, **kwargs):
            receipts.need(not calls, 'Second native call prohibited')
            payload = json.loads(request.data)
            receipts.need(payload['messages'][1]['content'] == case['source'], 'Frozen source drift')
            item = {'payload': payload, 'outcome': 'unknown', 'started_ns': time.time_ns()}
            calls.append(item)
            receipts.save(root / 'http-intent.json', item)
            try:
                response = real_open(request, *positional, **kwargs)
            except Exception as error:
                item.update(error_type=type(error).__name__, status=getattr(error, 'code', None))
                if hasattr(error, 'read'):
                    try:
                        raw = error.read(64 * 1024 + 1)
                        item.update(error_body_base64=base64.b64encode(raw).decode(),
                                    error_body_sha256=hashlib.sha256(raw).hexdigest(),
                                    error_body_truncated=len(raw) > 64 * 1024)
                    except Exception as read_error:
                        item['error_body_read_error'] = type(read_error).__name__
                    finally:
                        error.close()
                receipts.save(root / 'http-result.json', item)
                raise

            class ExactResponse:
                def __enter__(self):
                    return self
                def read(self, *read_args):
                    raw = response.read(*read_args)
                    item.update(outcome='response_read', status=response.status,
                                response_base64=base64.b64encode(raw).decode(),
                                response_sha256=hashlib.sha256(raw).hexdigest())
                    return raw
                def __exit__(self, *unused):
                    response.close()
                    receipts.save(root / 'http-result.json', item)
            return ExactResponse()

        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(16)
        server = uvicorn.Server(uvicorn.Config(gateway.app, log_level='error', lifespan='off'))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        receipts.need(server.started, 'Task-owned live HTTP server failed')
        base = 'http://127.0.0.1:' + str(listener.getsockname()[1])
        async with fixture.httpx.AsyncClient(base_url=base, trust_env=False, timeout=25) as client:
            bypass = []
            with patch.object(transport, 'open', side_effect=AssertionError('Unexpected native call')) as blocked:
                for query in ('?mode=raw', '?mode=raw&smart=true',
                              '?mode=smart&smart=true&format=false', '?format=false'):
                    response = await fixture.post(client, query)
                    receipts.need(response.status_code == 200 and
                                  response.headers['x-text-editor-status'] == 'bypassed', 'Opt-out failed')
                    record = gateway.voice_corpus.save.call_args.args[1]
                    receipts.need(response.json()['text'] == record['accepted_stt_text'], 'Opt-out provenance')
                    bypass.append({'query': query, 'status': response.status_code})
                blocked.assert_not_called()
            with patch.object(transport, 'open', side_effect=capture):
                response = await fixture.post(client, '?mode=' + case['mode'])
            record = gateway.voice_corpus.save.call_args.args[1]
            receipts.need(response.status_code == 200 and len(calls) == 1, 'Native seam did not execute once')
            receipts.need(record['accepted_stt_text'] == case['source'], 'Accepted-source drift')
            text = response.json()['text']
            quality = score(text, case)
            quality['editor_status'] = response.headers['x-text-editor-status']
            native = json.loads(base64.b64decode(calls[0]['response_base64'])) if calls[0].get('response_base64') else {}
            quality['native_eos'] = native.get('choices', [{}])[0].get('finish_reason') == 'stop'
            quality['passed'] = quality['rubric_passed'] and quality['native_eos'] and quality['editor_status'] == 'applied'
            with patch.object(transport, 'open', side_effect=ConnectionRefusedError('synthetic unavailable')) as refused:
                fallback = await fixture.post(client, '?mode=' + case['mode'], 'text')
                receipts.need(fallback.status_code == 200 and fallback.text == case['source'] and
                              fallback.headers['x-text-editor-status'] == 'fallback', 'Exact-source fallback failed')
                refused.assert_called_once()
                fallback_receipt = {'response_status': fallback.status_code,
                                    'response_text': fallback.text, 'headers': dict(fallback.headers),
                                    'record': gateway.voice_corpus.save.call_args.args[1],
                                    'injected': True, 'native_http_calls': 0}
        return {'case_id': case['id'], 'mode': case['mode'], 'native_http_calls': len(calls),
                'live_gateway_http': True, 'private_loopback': True, 'synthetic_asr_loqira': True,
                'real_audio_or_owner_field': False, 'http': calls, 'optouts': bypass,
                'response': response.json(), 'headers': dict(response.headers), 'record': record,
                'fallback_injected': fallback_receipt, 'quality': quality}
    finally:
        cleanup_receipt = {'at_ns': time.time_ns(), 'server_started': bool(server and server.started)}
        try:
            if server is not None:
                server.should_exit = True
            if thread is not None:
                thread.join(timeout=5)
                cleanup_receipt['thread_stopped'] = not thread.is_alive()
                receipts.need(not thread.is_alive(), 'Task-owned HTTP thread cleanup failed')
        finally:
            if listener is not None:
                listener.close()
                cleanup_receipt['listener_closed'] = listener.fileno() == -1
            cleanup_receipt['fixture_cleanups_passed'] = fixture.doCleanups()
            receipts.save(root / 'harness-cleanup.json', cleanup_receipt)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--fixtures-sha256', required=True)
    parser.add_argument('--gateway-sha256', required=True)
    parser.add_argument('--case-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.fixtures.read_bytes()
    receipts.need(hashlib.sha256(raw).hexdigest() == args.fixtures_sha256, 'Fixture drift')
    manifest = json.loads(raw)
    receipts.need(manifest['maximum_native_requests'] == 4 and len(manifest['cases']) == 4
                  and manifest['no_replay_or_output_repair'] is True, 'Rewrite contract drift')
    case = next(c for c in manifest['cases'] if c['id'] == args.case_id)
    receipts.need(not args.output.exists(), 'Existing case: collect, never replay')
    claim = receipts.claim_case(args, case)
    args.output.mkdir(mode=0o700, parents=True)
    receipts.save(args.output / 'intent.json', {'case': case, 'canonical_claim': str(claim),
                  'gateway_sha256': args.gateway_sha256, 'fixtures_sha256': args.fixtures_sha256})
    try:
        result = asyncio.run(execute(args, case, args.output))
    except BaseException as error:
        receipts.save(args.output / 'runner-error.json', {'type': type(error).__name__, 'message': str(error)})
        raise
    receipts.save(args.output / 'result.json', result)
    print(json.dumps(result, ensure_ascii=False))
    if not result['quality']['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
