"""Numerical-ID RNNT beam with open vocabulary, pair mask and context refund.

This is an isolated CPU prototype, not the installed sherpa recognizer. Decoder
state progression follows NeMo RNNT: blank advances time without consuming a
prediction token; a nonblank advances the prediction state at the same frame.
"""
from dataclasses import dataclass, replace
import math


class ContextBias:
    """Potential-based phrase bias; unfinished prefix credit is refunded.

    IDs are language-aware inputs, never reverse-looked-up token strings.
    Overlapping completed names earn only the longest completion at a step.
    """
    def __init__(self, paths=(), score=0.0):
        self.paths = tuple(sorted(set(tuple(p) for p in paths)))
        if not math.isfinite(score) or score < 0 or any(not p for p in self.paths):
            raise ValueError('Invalid context score or empty phrase')
        self.score = float(score)
        self.prefixes = {p[:i] for p in self.paths for i in range(1, len(p))}
        self.max_length = max(map(len, self.paths), default=0)

    def step(self, state, token):
        if not self.paths or self.score == 0:
            return 0.0, ()
        sequence = (*state, int(token))
        completed = max((len(p) for p in self.paths
                         if len(p) <= len(sequence) and sequence[-len(p):] == p), default=0)
        pending = max((p for p in self.prefixes
                       if len(p) <= len(sequence) and sequence[-len(p):] == p),
                      key=len, default=())
        return self.score * (completed + len(pending) - len(state)), pending

    def finalize(self, state):
        return -self.score * len(state)


def finite_topk(scores, allowed, count):
    """Never return forbidden/nonfinite IDs, even if beam exceeds vocabulary."""
    return sorted((i for i in allowed if math.isfinite(float(scores[i]))),
                  key=lambda i: (-float(scores[i]), i))[:count]


@dataclass
class Hypothesis:
    ids: tuple
    timestamps: tuple
    log_probs: tuple
    score: float
    frame: int
    symbols: int
    context: tuple
    states: object
    prediction: object = None


def merge_and_prune(candidates, beam):
    merged = {}
    for h in candidates:
        key = (h.ids, h.frame, h.symbols)
        old = merged.get(key)
        if old is None:
            merged[key] = h
        else:
            maximum = max(old.score, h.score)
            score = maximum + math.log1p(math.exp(-abs(old.score - h.score)))
            representative = h if h.score > old.score else old
            merged[key] = replace(representative, score=score)
    return sorted(merged.values(), key=lambda h: h.score, reverse=True)[:beam]


def decode(model, encoded, length, allowed, blank, context, beam=4,
           max_symbols=10, check=lambda: None):
    import numpy as np
    allowed = tuple(sorted(set(allowed) | {blank}))
    if beam < 1 or max_symbols < 1 or length < 1:
        raise ValueError('Invalid beam or encoded length')
    current = [Hypothesis((), (), (), 0.0, 0, 0, (), model.initial_states())]
    steps, emitted_limit_forced = 0, 0
    while True:
        check()
        frame = min(h.frame for h in current)
        if frame >= length:
            break
        candidates = []
        for h in current:
            if h.frame > frame:
                candidates.append(h)
                continue
            if h.prediction is None:
                token = h.ids[-1] if h.ids else blank
                h.prediction, h.states = model.predict(token, h.states)
            logits = model.join(encoded[:, :, frame:frame + 1], h.prediction)
            logits = np.asarray(logits, dtype=np.float64).reshape(-1)
            if blank != len(logits) - 1 or any(i < 0 or i >= len(logits) for i in allowed):
                raise ValueError('Model class dimension does not match verified vocabulary')
            if not np.isfinite(logits).all():
                raise ValueError('Nonfinite acoustic logits')
            log_probs = logits - np.max(logits)
            log_probs -= np.log(np.exp(log_probs).sum())
            adjusted = np.full(len(log_probs), -np.inf)
            transitions = {}
            for token in allowed:
                delta, state = (0.0, h.context) if token == blank else context.step(h.context, token)
                adjusted[token] = log_probs[token] + delta
                transitions[token] = (delta, state)
            # Cap pathological repeats but retain the actual acoustic blank cost.
            if h.symbols >= max_symbols:
                chosen = [blank]
                emitted_limit_forced += 1
            else:
                chosen = finite_topk(adjusted, allowed, beam)
            for token in chosen:
                if not math.isfinite(float(adjusted[token])):
                    continue
                delta, state = transitions[token]
                score = h.score + float(log_probs[token]) + delta
                if token == blank:
                    candidates.append(replace(h, score=score, frame=frame + 1, symbols=0))
                else:
                    candidates.append(Hypothesis(
                        (*h.ids, token), (*h.timestamps, frame),
                        (*h.log_probs, float(log_probs[token])), score, frame,
                        h.symbols + 1, state, h.states, None))
            steps += 1
        current = merge_and_prune(candidates, beam)
        if not current:
            raise RuntimeError('No finite allowed decoding path')
    best = max(current, key=lambda h: h.score + context.finalize(h.context))
    if any(i not in allowed or i == blank for i in best.ids):
        raise RuntimeError('Forbidden ID emitted')
    return {'token_ids': list(best.ids), 'frame_indices': list(best.timestamps),
            'acoustic_token_log_probs': list(best.log_probs),
            'final_score': best.score + context.finalize(best.context),
            'decoder_expansions': steps, 'forced_blank_count': emitted_limit_forced}
