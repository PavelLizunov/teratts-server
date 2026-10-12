"""Open CTC shallow fusion with a frozen probability-only language model.

Only acoustic RU/EN token paths can appear in output; LM has no generate call.
Score full provisional prefixes during search and EOS at finish.
"""
import argparse
from collections import OrderedDict, defaultdict
from functools import lru_cache
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

from ctc_context import search, equalize_branch_priors, WordLanguageConstraint
from decoder import ContextBias
from mms_pair import digest, save
from run import Guard, memory_snapshot, sensors
from pilot import rss_bytes

REVISION = 'a9307e696cd3c5b7f953ff4cb19d76a4d81821d5'
PARAMETERS = {'beam': 32, 'prebeam': 64, 'lm_alpha': .3, 'word_bonus': 1.0,
              'seconds': 600, 'rss_mib': 4096, 'kv_cache_mib': 256, 'threads': 2}


class LanguageScorer:
    def __init__(self, root, pieces, check):
        import torch
        from transformers import GPT2Config, GPT2LMHeadModel, GPT2TokenizerFast
        self.torch, self.pieces, self.check = torch, pieces, check
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
        assets = json.loads((root / 'download-receipt.json').read_text())
        if assets['revision'] != REVISION:
            raise ValueError('Wrong LM revision')
        for item in assets['files']:
            if digest(root / item['name']) != item['sha256']:
                raise ValueError('LM asset changed')
        config = GPT2Config.from_pretrained(root, local_files_only=True)
        self.model = GPT2LMHeadModel(config).eval()
        weights = torch.load(root / 'pytorch_model.bin', map_location='cpu', weights_only=True)
        # Legacy checkpoint stored deterministic causal masks as persistent
        # buffers. Modern GPT2 recreates them; verify their content, not ignore.
        removed = []
        for i in range(config.n_layer):
            key = f'transformer.h.{i}.attn.bias'
            expected = self.model.transformer.h[i].attn.bias
            if not torch.equal(weights[key].bool(), expected):
                raise ValueError('Unexpected legacy causal mask')
            del weights[key]
            key = f'transformer.h.{i}.attn.masked_bias'
            if weights[key].numel() != 1 or float(weights[key]) != -10000.:
                raise ValueError('Unexpected legacy attention sentinel')
            del weights[key]
            removed.extend([f'transformer.h.{i}.attn.bias', key])
        self.model.load_state_dict(weights, strict=True)
        if not torch.equal(weights['lm_head.weight'], weights['transformer.wte.weight']):
            raise ValueError('Expected tied embeddings in checkpoint')
        del weights
        self.tokenizer = GPT2TokenizerFast.from_pretrained(root, local_files_only=True)
        vocabulary = json.loads((root / 'vocab.json').read_text())
        if ((self.tokenizer.bos_token_id, self.tokenizer.eos_token_id, len(self.tokenizer)) != (1, 2, 50257)
                or self.tokenizer.get_vocab() != vocabulary or config.vocab_size != 50264
                or set(vocabulary.values()) != set(range(50257))):
            raise ValueError('Unexpected published tokenizer map or model projection')
        # Seven output slots are absent from publisher vocabulary. Keep the
        # original 50264-way softmax; never resize weights or invent token IDs.
        self.load_receipt = {'strict_parameters': True, 'removed_verified_nonlearned_buffers': removed,
                             'asset_receipt_sha256': digest(root / 'download-receipt.json'),
                             'runtime_model_source_sha256': digest(sys.modules[self.model.__class__.__module__].__file__)}
        self.prebeam, self.alpha, self.beta = PARAMETERS['prebeam'], PARAMETERS['lm_alpha'], PARAMETERS['word_bonus']
        self.cache, self.cache_bytes, self.peak_cache_bytes = OrderedDict(), 0, 0
        self.scores = {(1,): 0.0}
        self.text_scores = {('', False): (0., 0)}
        self.forward_calls = self.scored_sequences = self.processed_suffix_tokens = 0
        with torch.inference_mode():
            result = self.model.transformer(torch.tensor([[1]]), use_cache=True, return_dict=True)
            probs = self.model.lm_head(result.last_hidden_state[:, -1]).log_softmax(-1)[0]
        self.put((1,), result.past_key_values, probs, 0.0)
        self.forward_calls += 1

    def put(self, key, past, next_probs, score):
        if key in self.cache:
            _, _, _, size = self.cache.pop(key)
            self.cache_bytes -= size
        size = sum(t.numel() * t.element_size() for pair in past for t in pair) + next_probs.numel() * next_probs.element_size()
        self.cache[key] = (past, next_probs, score, size)
        self.cache_bytes += size
        self.peak_cache_bytes = max(self.peak_cache_bytes, self.cache_bytes)
        while self.cache_bytes > PARAMETERS['kv_cache_mib'] * 1048576 and len(self.cache) > 1:
            oldest = next(iter(self.cache))
            if oldest == (1,):
                self.cache.move_to_end(oldest)
                continue
            self.cache_bytes -= self.cache.pop(oldest)[3]

    @lru_cache(maxsize=100000)
    def text(self, prefix, final=False):
        visible = ''.join(self.pieces[t] for t in prefix).replace('▁', ' ').lstrip()
        if final:
            return visible.rstrip()
        # Provisional LM cost is essential: postponing unfinished-word cost
        # rewards unspaced strings during beam pruning. Re-tokenize full text.
        return visible

    def estimate(self, prefix):
        # Acoustic prebeam can use only known scores; an unseen word inherits
        # its scored text ancestor, then receives its true LM penalty below.
        while (self.text(prefix), False) not in self.text_scores:
            prefix = prefix[:-1]
        text = self.text(prefix)
        score, _ = self.text_scores[(text, False)]
        return self.alpha * score + self.beta * self.word_count(text, False)

    @staticmethod
    def word_count(text, final):
        return max(0, len(text.split()) - (0 if final or not text or text[-1].isspace() else 1))

    def score_texts(self, texts, final):
        torch = self.torch
        pending = {}
        for text in dict.fromkeys(texts):
            if (text, final) in self.text_scores:
                continue
            ids = (1, *self.tokenizer.encode(text, add_special_tokens=False), *((2,) if final else ()))
            if len(ids) > self.model.config.n_positions:
                raise ValueError('LM context would truncate an acoustic path')
            if ids in self.scores:
                self.text_scores[(text, final)] = (self.scores[ids], len(text.split()))
            else:
                pending[ids] = text
        groups = defaultdict(list)
        # Save references to parent KV states while the LRU can evict entries.
        for ids, text in pending.items():
            parent = ids[:-1]
            while parent not in self.cache:
                parent = parent[:-1]
            self.cache.move_to_end(parent)
            groups[(len(parent), len(ids) - len(parent))].append((ids, text, self.cache[parent]))
        for (plen, slen), group in groups.items():
            for begin in range(0, len(group), 8):
                self.check()
                batch = group[begin:begin + 8]
                suffix = torch.tensor([ids[plen:] for ids, _, _ in batch], dtype=torch.long)
                past = tuple(tuple(torch.cat([state[0][layer][kv] for _, _, state in batch], 0)
                                   for kv in (0, 1)) for layer in range(self.model.config.n_layer))
                base = torch.tensor([state[2] for _, _, state in batch], dtype=torch.float64)
                first = torch.stack([state[1][ids[plen]] for ids, _, state in batch]).double()
                with torch.inference_mode():
                    result = self.model.transformer(suffix, past_key_values=past, use_cache=True, return_dict=True)
                    logits = self.model.lm_head(result.last_hidden_state).log_softmax(-1)
                    rest = logits[:, :-1].gather(-1, suffix[:, 1:, None]).squeeze(-1).double().sum(-1)
                    totals = base + first + rest
                self.forward_calls += 1
                self.scored_sequences += len(batch)
                self.processed_suffix_tokens += len(batch) * slen
                for i, (ids, text, _) in enumerate(batch):
                    score = float(totals[i])
                    state = tuple(tuple(t[i:i+1].clone() for t in pair) for pair in result.past_key_values)
                    self.put(ids, state, logits[i, -1].clone(), score)
                    self.scores[ids] = score
                    self.text_scores[(text, final)] = (score, len(text.split()))
                self.check()

    def prepare(self, prefixes, final=False):
        self.score_texts([self.text(p, final) for p in prefixes], final)

    def credit(self, prefix, final=False):
        text = self.text(prefix, final)
        score, _ = self.text_scores[(text, final)]
        return self.alpha * score + self.beta * self.word_count(text, final)

    def receipt(self, prefix):
        text = self.text(prefix, True)
        score, words = self.text_scores[(text, True)]
        return {'lm_log_prob': score, 'lm_alpha': self.alpha, 'lm_words': words,
                'lm_word_bonus': self.beta, 'lm_credit': self.credit(prefix, True),
                'lm_scored_text': text, 'lm_eos_scored': True}

    def observe_best_score(self, prefix):
        # Direct consistency observation on the actual output, not a synthetic
        # test or another ASR decode: compare cached sums with teacher forcing.
        torch = self.torch
        text = self.text(prefix, True)
        ids = torch.tensor([[1, *self.tokenizer.encode(text, add_special_tokens=False), 2]])
        with torch.inference_mode():
            hidden = self.model.transformer(ids[:, :-1], use_cache=False).last_hidden_state
            lp = self.model.lm_head(hidden).log_softmax(-1)
            score = float(lp.gather(-1, ids[:, 1:, None]).double().sum())
        cached = self.text_scores[(text, True)][0]
        error = abs(score - cached)
        if error > .005:
            raise ValueError('Cached LM probability differs from direct score')
        self.forward_calls += 1
        return {'teacher_forced_log_prob': score, 'cached_log_prob': cached, 'absolute_error': error}


def cell(args):
    import numpy as np
    output, root = Path(args.output), Path(args.root)
    if output.exists():
        raise FileExistsError('Consumed LM decode')
    guard = Guard(PARAMETERS['seconds'], PARAMETERS['rss_mib'])
    started = time.monotonic()
    result = {'status': 'failed', 'parameters': PARAMETERS, 'encoder_rerun': False,
              'language_model_generates_text': False, 'postprocessing': 'none',
              'source_commit': subprocess.check_output(['git', '-C', str(Path(__file__).parent), 'rev-parse', 'HEAD'], text=True).strip(),
              'host': os.uname().nodename, 'variants': {}}
    scorer = None
    try:
        original = json.loads(Path(args.receipt).read_text())
        retained = Path(args.receipt).with_suffix('.npz')
        if digest(retained) != original['retained_logits_sha256']:
            raise ValueError('Retained ASR logits changed')
        artifacts = json.loads((root / 'fastconformer-pilot/prepared-artifacts.json').read_text())
        vocab = root / 'fastconformer-pilot/int8/tokens.txt'
        if digest(vocab) != artifacts['files_sha256']['tokens.txt']:
            raise ValueError('Acoustic token map changed')
        pieces = {int(line.rsplit(' ', 1)[1]): line.rsplit(' ', 1)[0] for line in vocab.read_text().splitlines()}
        # Reuse the already verified hint paths in the prior result. No text
        # target or previous transcript is used as an input to the LM.
        previous = json.loads(Path(args.context_receipt).read_text())
        if previous['original_audio_sha256'] != original['audio_sha256']:
            raise ValueError('Wrong retained hint-path receipt')
        hint_receipts = previous['variants']['context']['context_paths']
        paths = [p['token_ids'] for p in hint_receipts]
        with np.load(retained) as file:
            lp, correction = equalize_branch_priors(file['log_probs'], artifacts)
        rule = WordLanguageConstraint(artifacts, pieces)
        scorer = LanguageScorer(Path(args.model), pieces, guard.check)
        guard.check()
        result.update(audio_sha256=original['audio_sha256'], parent_receipt_sha256=digest(args.receipt),
                      context_receipt_sha256=digest(args.context_receipt), language_prior_correction=correction,
                      lm_loading=scorer.load_receipt, load_s=time.monotonic() - started)
        for name, bonus in (('no-hints', 0.0), ('context', 2.5)):
            before = time.monotonic()
            graph = ContextBias(paths if bonus else (), bonus)
            hypotheses = search(lp, artifacts['allowed_token_ids'], artifacts['blank_id'], graph,
                                PARAMETERS['beam'], guard.check, rule, scorer)
            for h in hypotheses:
                h['prior_adjusted_acoustic_log_prob'] = h.pop('acoustic_log_prob')
                h['raw_text'] = ''.join(pieces[t] for t in h['token_ids']).replace('▁', ' ').strip()
                h['postprocessed_text'] = h['raw_text']
                h['word_language_rule'] = rule.receipt(h['token_ids'])
                if h['word_language_rule']['within_word_violations'] or any(t not in artifacts['allowed_token_ids'] for t in h['token_ids']):
                    raise ValueError('Invalid numerical language path')
                if h['context_credit'] > bonus * len(h['token_ids']) + 1e-8:
                    raise ValueError('Context union credit exceeded')
            direct = scorer.observe_best_score(tuple(hypotheses[0]['token_ids']))
            variant = {'decode_s': time.monotonic() - before, 'hint_bonus': bonus,
                       'context_paths': hint_receipts if bonus else [], 'hypotheses': hypotheses,
                       'best_score_consistency': direct}
            save(output.with_name(output.stem + '-' + name + '.json'), variant)
            result['variants'][name] = variant
            print(name, hypotheses[0]['raw_text'], flush=True)
        result['status'] = 'success'
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        if scorer:
            result['lm_work'] = {'forward_calls': scorer.forward_calls, 'scored_sequences': scorer.scored_sequences,
                                 'processed_suffix_tokens': scorer.processed_suffix_tokens,
                                 'peak_kv_cache_bytes': scorer.peak_cache_bytes}
        result.update(elapsed_s=time.monotonic() - started,
                      peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                      guard=guard.receipt())
        save(output, result)
        print(json.dumps({k: v for k, v in result.items() if k != 'variants'}, ensure_ascii=False), flush=True)


def pilot(args, cell_script=None):
    manifest = json.loads(Path(args.manifest).read_text())
    results = Path(manifest['results_directory'])
    results.mkdir(mode=0o700, exist_ok=False)
    baseline = memory_snapshot()
    for clip in manifest['recordings']:
        output = results / (clip['id'] + '.json')
        command = [sys.executable, str(Path(cell_script or __file__).resolve()), 'cell', '--root', manifest['root'],
                   '--model', manifest['model'], '--receipt', clip['receipt'], '--context-receipt', clip['context_receipt'],
                   '--output', str(output)]
        started, peak, reason, samples = time.monotonic(), 0, None, []
        with output.with_suffix('.stdout').open('xb') as out, output.with_suffix('.stderr').open('xb') as err:
            process = subprocess.Popen(['nice', '-n', '19', *command], stdout=out, stderr=err,
                                       env=dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                                                OPENBLAS_NUM_THREADS='2', OMP_NUM_THREADS='2'))
            try:
                while process.poll() is None:
                    peak = max(peak, rss_bytes(process.pid))
                    mem, thermal = memory_snapshot(), sensors()
                    sample = {'elapsed_s': time.monotonic() - started, 'rss_bytes': peak,
                              'available_bytes': mem['MemAvailable'], 'swap_growth_bytes': mem['swap_used'] - baseline['swap_used'], **thermal}
                    samples.append(sample)
                    if peak > PARAMETERS['rss_mib'] * 1048576: reason = 'rss_limit'
                    if mem['MemAvailable'] < 2048 * 1048576: reason = 'available_memory_floor'
                    if sample['swap_growth_bytes'] > 256 * 1048576: reason = 'swap_limit'
                    if any(t >= 85000 for t in thermal['temperatures_millic'].values()): reason = 'thermal_limit'
                    if time.monotonic() - started > PARAMETERS['seconds'] + 5: reason = 'timeout'
                    if reason: break
                    time.sleep(.5)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill()
                code = process.wait()
        save(output.with_name(output.stem + '-supervisor.json'),
             {'exit_code': code, 'stop_reason': reason, 'elapsed_s': time.monotonic() - started,
              'peak_rss_bytes': peak, 'samples': samples, 'command': command,
              'manifest_sha256': digest(args.manifest), 'limits_source': 'agent-selected method protection'})
        print(clip['id'], 'exit', code, 'stop', reason, flush=True)
        if code or reason:
            raise RuntimeError('Cell stopped; preserve partial outputs, remaining cells untouched')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='mode', required=True)
    c = sub.add_parser('cell')
    for key in ('root', 'model', 'receipt', 'context-receipt', 'output'):
        c.add_argument('--' + key, required=True)
    p = sub.add_parser('pilot')
    p.add_argument('manifest')
    args = parser.parse_args()
    if args.mode == 'cell': cell(args)
    else: pilot(args)
