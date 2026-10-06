"""Conservative punctuation/case restoration; never accept changed transcript words."""
import re
from difflib import SequenceMatcher
import threading

TOKEN = re.compile(r"https?://\S+|[\w]+(?:[./:@+\-][\w]+)*|`[^`]*`", re.UNICODE)


def words(text):
    return [m.group(0).casefold() for m in TOKEN.finditer(text)]


def basic_format(text):
    """Failure fallback only: sentence case and a terminal full stop."""
    if not text.strip():
        return text
    result = text.strip()
    for match in re.finditer(r"[^\W\d_]", result):
        if 'а' <= match.group().lower() <= 'я' or match.group().lower() == 'ё':
            i = match.start(); result = result[:i] + result[i].upper() + result[i + 1:]
        break
    if result[-1].isalnum():
        result += '.'
    return result


def contextual_english(text):
    """Explicit scoped English spelling, not universal Russian transliteration."""
    changes = []
    cue = re.compile(r'(?:английск\w*\s+(?:выражени\w*|услови\w*|оператор\w*|слов\w*)\s+)(ор\s+нот)\b', re.I)
    def replace(match):
        start, end = match.span(1)
        changes.append({'start': start, 'end': end, 'before': match.group(1), 'after': 'or not',
                        'rule': 'explicit-english-context-or-not'})
        return match.group()[:start - match.start()] + 'or not'
    protected = [m.span() for m in re.finditer(r'https?://\S+|`[^`]*`', text)]
    def safe_replace(match):
        if any(a <= match.start() < b or a < match.end() <= b for a, b in protected):
            return match.group()
        prefix = text[max(0, match.start()-8):match.start()]
        if re.search(r'\bне\s*$', prefix, re.I):
            return match.group()
        return replace(match)
    output = cue.sub(safe_replace, text)
    return output, {'status': 'applied' if changes else 'unchanged', 'changes': changes,
                    'policy': 'explicit-english-context-v1', 'input_text': text, 'output_text': output}


def validate_format(original, candidate):
    if not isinstance(candidate, str) or not candidate.strip():
        return False
    if '```' in candidate or len(candidate) > max(256, len(original) * 2):
        return False
    # Permit punctuation/case only. Numbers, negations, repetitions and words are exact.
    if words(original) != words(candidate):
        return False
    # Protect non-Russian tokens byte-for-byte (English names, URLs, code and paths).
    src = list(TOKEN.finditer(original)); dst = list(TOKEN.finditer(candidate))
    return all(a.group() == b.group() for a, b in zip(src, dst)
               if re.search(r'[A-Za-z/\\@`]', a.group()))


def project_punctuation(original, candidate):
    """Take punctuation only between adjacent aligned words; never copy generated words."""
    if not isinstance(candidate, str) or not candidate.strip() or '```' in candidate:
        return basic_format(original)
    src, dst = list(TOKEN.finditer(original)), list(TOKEN.finditer(candidate))
    aligned = {}
    matcher = SequenceMatcher(a=[m.group().casefold() for m in src],
                              b=[m.group().casefold() for m in dst], autojunk=False)
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            aligned[block.a + k] = block.b + k
    result = original[:src[0].start()] if src else original
    for i, token in enumerate(src):
        value = token.group()
        target = aligned.get(i)
        if target is not None and not re.search(r'[A-Za-z/\\@`]', value):
            value = dst[target].group()
        result += value
        end = src[i + 1].start() if i + 1 < len(src) else len(original)
        separator = original[token.end():end]
        next_target = aligned.get(i + 1)
        if target is not None and next_target == target + 1:
            offered = candidate[dst[target].end():dst[next_target].start()]
            # Only punctuation/whitespace; don't replace existing explicit separators.
            if separator.isspace() and re.fullmatch(r'[\s,.;:!?—–-]{1,8}', offered):
                separator = offered
        elif i + 1 == len(src) and target == len(dst) - 1 and not separator.strip():
            offered = candidate[dst[target].end():]
            if re.fullmatch(r'[\s.!?]{0,4}', offered):
                separator = offered
        result += separator
    return result.strip()


class Formatter:
    """Serialize SAGE CPU inference; chunk by tokens to avoid output truncation."""
    def __init__(self, run_sage):
        self.run_sage = run_sage
        self.lock = threading.Lock()

    def __call__(self, text):
        meta = {'engine': 'sage95m-onnx-cpu', 'policy': 'punctuation-case-only-v1',
                'status': 'empty', 'segments': [], 'input_text': text}
        if not text.strip():
            return text, meta
        matches = list(TOKEN.finditer(text))
        # Small bounded segments; original words retained even when SAGE edits them.
        boundaries = [matches[i].start() for i in range(48, len(matches), 48)]
        boundaries = [0] + boundaries + [len(text)]
        results = []
        with self.lock:
            for start, end in zip(boundaries, boundaries[1:]):
                source = text[start:end].strip()
                try:
                    candidate, complete = self.run_sage(source)
                    accepted = complete and validate_format(source, candidate)
                    status = 'applied' if accepted else 'rejected_lexical_change_or_incomplete'
                except Exception:
                    candidate, accepted, complete, status = None, False, False, 'failed'
                if not accepted and not complete:
                    candidate_for_projection = None
                else:
                    candidate_for_projection = candidate
                output = candidate.strip() if accepted else basic_format(project_punctuation(source, candidate_for_projection))
                results.append(output)
                meta['segments'].append({'input_text': source, 'candidate_text': candidate,
                                         'output_text': output, 'status': status})
        output = ' '.join(results)
        # Safety independent from SAGE and segmentation: all original tokens survive.
        if not validate_format(text, output):
            output = basic_format(text)
            meta['status'] = 'failed_fidelity'
        else:
            meta['status'] = 'applied' if all(s['status'] == 'applied' for s in meta['segments']) else 'fallback_preserved_words'
        return output, meta
