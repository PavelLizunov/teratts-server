#!/usr/bin/env python3
"""Bounded, single-profile correction screen; private inputs/results stay outside Git."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import threading
import time
import urllib.request

SYSTEM = 'Отформатируй текст голосового ввода: расставь пунктуацию и заглавные буквы, разбей на абзацы, исправь опечатки и орфографические ошибки. Сохрани язык, слова и смысл, ничего не добавляй от себя.'
MODEL_SHA = '893f573db88f587e823b66847e06049cdb3029eff6177d92f6577179f7178871'
PILOT_SHA = 'b1e64f5b0e6349deefc3534358cbe97becac78349ae5ddc3a28c380ac9974a6d'
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def request(url, payload=None, timeout=45):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    with HTTP.open(req, timeout=timeout) as response:
        return json.load(response)


def sha(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def words(text):
    return re.findall(r'\w+', text.casefold().replace('ё', 'е'))


def distance(a, b):
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        new = [i]
        for j, y in enumerate(b, 1):
            new.append(min(new[-1] + 1, row[j] + 1, row[j-1] + (x != y)))
        row = new
    return row[-1]


def resources():
    mem = {k: int(v.split()[0]) for k, v in (s.split(':', 1) for s in Path('/proc/meminfo').read_text().splitlines())}
    sensors = {}
    for p in Path('/sys/class/hwmon').glob('*/temp*_input'):
        try:
            sensors[str(p)] = int(p.read_text()) / 1000
        except OSError:
            pass
    fans = {}
    for p in Path('/sys/class/hwmon').glob('*/fan*_input'):
        try:
            fans[str(p)] = int(p.read_text())
        except OSError:
            pass
    return {'utc': datetime.now(timezone.utc).isoformat(), 'available_mib': mem['MemAvailable']/1024,
            'swap_used_mib': (mem['SwapTotal']-mem['SwapFree'])/1024,
            'temperature_c': sensors, 'fan_rpm': fans}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--cases', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    out = Path(args.output); out.mkdir(exist_ok=False)
    def save(name, data):
        with (out/name).open('x') as target:
            json.dump(data, target, ensure_ascii=False, indent=2)
    started = time.monotonic()
    assert sha(args.model) == MODEL_SHA
    cases = [json.loads(line) for line in Path(args.cases).read_text().splitlines()]
    before = request('http://127.0.0.1:10000/readyz', timeout=5)
    assert before['stt_model']['model_sha256'] == PILOT_SHA
    baseline = resources()
    assert baseline['available_mib'] >= 2300, baseline
    command = [args.engine, '-m', args.model, '--alias', 'loqira-trial', '--host', '127.0.0.1', '--port', '10004',
               '-c', '2048', '-np', '1', '-b', '256', '-ub', '128', '-ngl', 'all', '-t', '2', '-tb', '2',
               '-ctk', 'f16', '-ctv', 'f16', '--fit', 'off', '--cache-ram', '0', '--no-webui', '--no-context-shift',
               '-fa', 'on', '--jinja', '--reasoning', 'off', '--chat-template-kwargs', '{"enable_thinking":false}']
    save('manifest.json', {'command': command, 'model_sha': MODEL_SHA, 'engine_sha': sha(args.engine),
                          'cases_sha': sha(args.cases), 'system_prompt': SYSTEM,
                          'git_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                          'version': subprocess.run([args.engine, '--version'], text=True, capture_output=True).stderr,
                          'baseline': baseline, 'production_before': before, 'cases': len(cases)})
    stop = threading.Event(); guard = []; samples = []; rows = []; error = None
    log = (out/'server.log').open('x')
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
    save('process.json', {'pid': process.pid, 'utc': datetime.now(timezone.utc).isoformat()})
    def monitor():
        with (out/'resources.jsonl').open('x') as stream:
            while not stop.is_set():
                sample = resources(); samples.append(sample)
                stream.write(json.dumps(sample)+'\n'); stream.flush()
                reasons = []
                if sample['available_mib'] < 1536: reasons.append('memory_headroom')
                if sample['swap_used_mib'] - baseline['swap_used_mib'] > 256: reasons.append('swap_growth')
                if max(sample['temperature_c'].values(), default=0) >= 85: reasons.append('temperature')
                if reasons:
                    guard.extend(reasons); process.terminate(); return
                stop.wait(1)
    monitor_thread = threading.Thread(target=monitor, daemon=True); monitor_thread.start()
    try:
        deadline = time.monotonic() + 90
        while True:
            if process.poll() is not None: raise RuntimeError(f'server_exit={process.returncode}, guard={guard}')
            try:
                health = request('http://127.0.0.1:10004/health', timeout=2)
                if health.get('status') == 'ok': break
            except (OSError, ValueError):
                pass
            if time.monotonic() > deadline: raise TimeoutError('startup90s')
            stop.wait(0.5)
        save('props.json', request('http://127.0.0.1:10004/props'))
        models = request('http://127.0.0.1:10004/v1/models'); save('models.json', models)
        assert models['data'][0]['id'] == 'loqira-trial'
        smoke_messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': cases[0]['input']}]
        rendered = request('http://127.0.0.1:10004/apply-template', {'messages': smoke_messages, 'add_generation_prompt': True, 'chat_template_kwargs': {'enable_thinking': False}})
        save('template.json', rendered)
        expected = '<|im_start|>system\n'+SYSTEM+'<|im_end|>\n<|im_start|>user\n'+cases[0]['input']+'<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
        assert rendered['prompt'] == expected, 'author_template_mismatch'
        deadline = time.monotonic() + 600
        for case in cases:
            if guard: raise RuntimeError(str(guard))
            if time.monotonic() >= deadline: raise TimeoutError('screen600s')
            payload = {'model': 'loqira-trial', 'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': case['input']}],
                       'temperature': 0, 'repeat_penalty': 1.0, 'seed': 42, 'max_tokens': 512, 'stream': False,
                       'stop': ['<|im_end|>'], 'chat_template_kwargs': {'enable_thinking': False}, 'cache_prompt': False}
            save(case['id']+'-started.json', payload)
            t = time.monotonic(); result = request('http://127.0.0.1:10004/v1/chat/completions', payload)
            latency = time.monotonic()-t
            save(case['id']+'-response.json', result)
            choice = result['choices'][0]; text = choice['message']['content']
            assert choice['finish_reason'] == 'stop', 'incomplete_output'
            assert not choice['message'].get('reasoning_content') and '<think>' not in text, 'thinking_enabled'
            assert result['usage']['prompt_tokens']+512 <= 2048, 'input_budget'
            row = {**case, 'output': text, 'wall_s': latency, 'usage': result['usage'], 'timings': result.get('timings')}
            if case.get('reference'):
                ref = words(case['reference'])
                row.update(reference_words=len(ref), raw_edits=distance(ref, words(case['input'])), corrected_edits=distance(ref, words(text)))
            latin = Counter(re.findall(r'[A-Za-z]+', case['input']))
            row['input_latin_count'] = sum(latin.values())
            row['retained_latin_count'] = sum((latin & Counter(re.findall(r'[A-Za-z]+', text))).values())
            row['missing_literals'] = [value for value in case.get('preserve', []) if value not in text]
            rows.append(row)
            with (out/'rows.jsonl').open('a') as stream:
                stream.write(json.dumps(row, ensure_ascii=False)+'\n')
            print(json.dumps({'case': case['id'], 'wall_s': round(latency, 3), 'finish': choice['finish_reason']}, ensure_ascii=False), flush=True)
    except Exception as exc:
        error = repr(exc)
        raise
    finally:
        process.terminate()
        try: process.wait(timeout=15)
        except subprocess.TimeoutExpired: process.kill(); process.wait()
        stop.set(); monitor_thread.join(timeout=3); log.close()
        after = request('http://127.0.0.1:10000/readyz', timeout=10)
        save('summary.json', {'completed': len(rows), 'expected': len(cases), 'error': error, 'guard': guard,
                             'elapsed_s': time.monotonic()-started, 'server_returncode': process.returncode,
                             'production_after': after, 'min_available_mib': min(s['available_mib'] for s in samples),
                             'max_temperature_c': max(max(s['temperature_c'].values(), default=0) for s in samples),
                             'max_swap_growth_mib': max(s['swap_used_mib'] for s in samples)-baseline['swap_used_mib'],
                             'median_wall_s': statistics.median(r['wall_s'] for r in rows) if rows else None})
        assert after['stt_model']['model_sha256'] == PILOT_SHA


if __name__ == '__main__':
    main()
