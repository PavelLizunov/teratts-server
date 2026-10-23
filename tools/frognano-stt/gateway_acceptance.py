#!/usr/bin/env python3
"""Once-only installed-gateway synthetic test; no actual ASR/Loqira inference.

Use only with fresh frozen fixtures and externally verified committed sources.
Each case retains an exclusive intent before its single real optional HTTP call.
An existing intent is never replayed. Default/raw and unavailable checks are
model-free; they use the same installed handler and actual dictionary/cleanup.
"""
import argparse
import asyncio
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch


def need(ok, message):
    if not ok:
        raise RuntimeError(message)


def save(path, data):
    with path.open('x') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


async def execute(args, case, root):
    homelab = Path.home() / 'homelab'
    installed = homelab / 'gateway/server.py'
    need(hashlib.sha256(installed.read_bytes()).hexdigest() == args.gateway_sha256, 'Installed gateway drift')
    os.environ['BONSAI_ASGI_TEST'] = '1'
    os.environ['BONSAI_GATEWAY_TEST_SOURCE'] = str(installed)
    tests = Path(__file__).resolve().parents[1] / 'bonsai-normalizer/tests/test_gateway_asgi.py'
    harness = module('r73_asgi_acceptance_harness', tests)
    fixture = harness.TestFullGatewayASGI('test_real_multipart_precedence_provenance_and_formats')
    fixture.setUp()
    try:
        fixture.network.stop()  # Only the explicit real FrogNano client may contact HTTP below.
        gateway = fixture.gateway
        gateway.run_parakeet = lambda _: case['raw_asr_stub']
        gateway.loqira_corrector = lambda _: (case['loqira_stub'], {
            'status': 'applied', 'loqira_ms': 0.0, 'sage_ms': 0.0})
        os.environ['STT_DICTIONARY_CONFIG'] = str(homelab / 'config/stt-dictionary.json')
        os.environ.pop('BONSAI_NORMALIZER_CONFIG', None)
        config = homelab / 'config/frognano-normalizer.json'
        os.environ['FROGNANO_NORMALIZER_CONFIG'] = str(config)
        module('gateway.bonsai_normalizer', homelab / 'gateway/bonsai_normalizer.py')
        cleanup = homelab / 'gateway/frognano_cleanup.py'
        if cleanup.is_file():
            module('gateway.frognano_cleanup', cleanup)
        client = module('gateway.frognano_normalizer', homelab / 'gateway/frognano_normalizer.py')
        normalizer = client.get_frognano_normalizer(str(config))
        need(normalizer is not None, 'Installed FrogNano configuration disabled')
        gateway.bonsai_normalizer = normalizer
        records = []
        calls = []
        real_open = normalizer._opener.open

        def capture(request, *positional, **kwargs):
            need(not calls, 'Second native call prohibited')
            item = {'payload': json.loads(request.data), 'outcome': 'unknown', 'started_ns': time.time_ns()}
            calls.append(item)
            save(root / 'http-intent.json', item)
            try:
                response = real_open(request, *positional, **kwargs)
            except Exception as error:
                item.update(error_type=type(error).__name__, status=getattr(error, 'code', None))
                if getattr(error, 'code', None) is not None:
                    item['outcome'] = 'http_error_response'
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
            return ExactResponse()

        async with fixture.httpx.AsyncClient(transport=fixture.transport, base_url='http://installed-asgi.test') as http:
            # These calls must never contact any optional HTTP endpoint.
            with patch.object(normalizer._opener, 'open', side_effect=AssertionError('Unexpected model request')) as blocked:
                for mode in ('default', 'raw'):
                    response = await fixture.post(http, '?mode=' + mode + '&cleanup=true')
                    need(response.status_code == 200, 'Bypass request failed')
                    record = gateway.voice_corpus.save.call_args.args[1]
                    need(response.json()['text'] == record['accepted_stt_text'], 'Bypass provenance mismatch')
                    need(response.headers['x-text-editor-status'] == 'bypassed', 'Bypass status mismatch')
                    records.append({'mode': mode, 'response': response.json(), 'record': record,
                                    'headers': dict(response.headers)})
                blocked.assert_not_called()
            with patch.object(normalizer._opener, 'open', side_effect=capture):
                response = await fixture.post(http, '?mode=smart&cleanup=true')
                record = gateway.voice_corpus.save.call_args.args[1]
                records.append({'mode': 'smart', 'response_status': response.status_code,
                                'response': response.json(), 'record': record,
                                'headers': dict(response.headers)})
                need(response.status_code == 200 and len(calls) == 1, 'Native seam did not execute once')
                need(calls[0]['payload']['messages'][1]['content'] == record['accepted_stt_text'], 'Native input provenance mismatch')
            # A transport failure here is injected locally, never a second real request.
            with patch.object(normalizer._opener, 'open', side_effect=ConnectionRefusedError('synthetic unavailable')) as refused:
                response = await fixture.post(http, '?mode=smart&cleanup=true', 'text')
                record = gateway.voice_corpus.save.call_args.args[1]
                need(response.text == record['accepted_stt_text'], 'Unavailable fallback bytes changed')
                need(response.headers['x-text-editor-status'] == 'fallback', 'Unavailable fallback status')
                refused.assert_called_once()
                records.append({'mode': 'smart_unavailable_injected', 'response_text': response.text,
                                'record': record, 'headers': dict(response.headers)})
        return {'case_id': case['id'], 'gateway_sha256': args.gateway_sha256,
                'fixture_sha256': args.fixtures_sha256, 'native_http_calls': len(calls),
                'http': calls, 'checks': records, 'real_audio_or_owner_field': False}
    finally:
        fixture.doCleanups()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--fixtures-sha256', required=True)
    parser.add_argument('--gateway-sha256', required=True)
    parser.add_argument('--case-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.fixtures.read_bytes()
    need(hashlib.sha256(raw).hexdigest() == args.fixtures_sha256, 'Fixture drift')
    manifest = json.loads(raw)
    case = next(c for c in manifest['cases'] if c['id'] == args.case_id)
    need(manifest['maximum_native_requests'] == 2 and manifest['no_replay_or_output_repair'] is True, 'Trial contract drift')
    need(not args.output.exists(), 'Existing case: collect, never replay')
    args.output.mkdir(mode=0o700, parents=True)
    save(args.output / 'intent.json', {'case': case, 'pid': os.getpid(), 'started_ns': time.time_ns(),
                                     'fixtures_sha256': args.fixtures_sha256,
                                     'gateway_sha256': args.gateway_sha256})
    try:
        result = asyncio.run(execute(args, case, args.output))
    except BaseException as error:
        save(args.output / 'runner-error.json', {'type': type(error).__name__, 'message': str(error)})
        raise
    save(args.output / 'result.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
