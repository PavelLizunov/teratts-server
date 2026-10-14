"""Loqira text editing for the pilot gateway, with attributable SAGE fallback."""
import json
import re
import time
import urllib.request

MODEL_SHA = '893f573db88f587e823b66847e06049cdb3029eff6177d92f6577179f7178871'
MODEL = 'loqira-gec-0.8b-' + MODEL_SHA[:12]
REVISION = 'ced469768d40dffc899fe459efb66a4a07aeabee'
POLICY = 'loqira-lexical-correction-v1'
SYSTEM = 'Отформатируй текст голосового ввода: расставь пунктуацию и заглавные буквы, разбей на абзацы, исправь опечатки и орфографические ошибки. Сохрани язык, слова и смысл, ничего не добавляй от себя.'
IDENTITY = {'model': MODEL, 'model_sha256': MODEL_SHA, 'revision': REVISION, 'quantization': 'Q4_0'}


class LoqiraCorrector:
    def __init__(self, fallback):
        self.fallback = fallback
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, path, payload=None, timeout=20):
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        req = urllib.request.Request('http://127.0.0.1:10004' + path, data=data,
                                     headers={'Content-Type': 'application/json'})
        with self.http.open(req, timeout=timeout) as response:
            return json.load(response)

    def ready(self):
        try:
            health = self.request('/health', timeout=2)
            models = self.request('/v1/models', timeout=2)
            return health.get('status') == 'ok' and models['data'][0]['id'] == MODEL
        except Exception:
            return False

    @staticmethod
    def messages(text):
        return [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': text}]

    def __call__(self, text):
        meta = {'engine': 'loqira-0.8b-llama.cpp', **IDENTITY, 'policy': POLICY,
                'status': 'empty', 'input_text': text, 'segments': [], 'loqira_ms': 0, 'sage_ms': 0}
        if not text.strip():
            return text, meta
        deadline = time.monotonic() + 60
        def call(path, payload=None):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('correction_budget')
            started = time.perf_counter()
            try:
                return self.request(path, payload, min(20, remaining))
            finally:
                meta['loqira_ms'] += (time.perf_counter() - started) * 1000

        def process(start, end):
            source = text[start:end].strip()
            row = {'start': start, 'end': end, 'input_text': source, 'candidate_text': None}
            try:
                messages = self.messages(source)
                template = call('/apply-template', {'messages': messages, 'add_generation_prompt': True,
                                                    'chat_template_kwargs': {'enable_thinking': False}})['prompt']
                expected = '<|im_start|>system\n'+SYSTEM+'<|im_end|>\n<|im_start|>user\n'+source+'<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
                if template != expected:
                    raise ValueError('template_mismatch')
                count = len(call('/tokenize', {'content': template, 'add_special': False})['tokens'])
                row['prompt_tokens'] = count
                if count > 640:
                    cuts = [m.end() for m in re.finditer(r'\s+', text[start:end]) if m.end() < end-start]
                    if not cuts:
                        raise ValueError('unsplittable_overlong_token')
                    middle = (end-start)/2
                    sentence_cuts = [n for n in cuts if text[start+n-1:start+n].isspace()
                                     and re.search(r'[.!?]\s+$', text[start:start+n]) and middle/2 < n < middle*1.5]
                    cut = start + min(sentence_cuts or cuts, key=lambda n: abs(n-middle))
                    return process(start, cut) + '\n\n' + process(cut, end)
                result = call('/v1/chat/completions', {'model': MODEL, 'messages': messages,
                              'temperature': 0, 'repeat_penalty': 1.0, 'seed': 42, 'max_tokens': 1024,
                              'stop': ['<|im_end|>'], 'stream': False, 'cache_prompt': False,
                              'chat_template_kwargs': {'enable_thinking': False}})
                choice = result['choices'][0]
                candidate = choice['message']['content']
                row['candidate_text'] = candidate
                row['usage'] = result.get('usage')
                row['timings'] = result.get('timings')
                row['finish_reason'] = choice.get('finish_reason')
                if result.get('model') != MODEL:
                    raise ValueError('model_mismatch')
                if choice['finish_reason'] != 'stop':
                    raise ValueError('incomplete_generation')
                if not isinstance(candidate, str) or not candidate.strip():
                    raise ValueError('empty_output')
                if choice['message'].get('reasoning_content') or '<think>' in candidate:
                    raise ValueError('unexpected_reasoning')
                output = candidate.strip()
                row['status'] = 'applied'
            except Exception as exc:
                row['status'] = 'fallback_sage'
                row['reason'] = type(exc).__name__ + ': ' + str(exc)[:160]
                started = time.perf_counter()
                output, fallback_meta = self.fallback(source)
                meta['sage_ms'] += (time.perf_counter() - started) * 1000
                row['fallback'] = fallback_meta
            row['output_text'] = output
            meta['segments'].append(row)
            return output

        output = process(0, len(text))
        meta['status'] = 'applied' if all(s['status'] == 'applied' for s in meta['segments']) else 'fallback_sage'
        meta['output_text'] = output
        return output, meta
