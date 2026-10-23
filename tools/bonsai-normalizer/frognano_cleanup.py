"""Finite source-owned edits, not a general Russian profanity classifier.

The model may keep or delete only inventoried interjections. All other characters
must match the source; returned text is built from source slices, never model prose.
"""
import re

# Keep exact forms: root matching would eat names, literal nouns and technical terms.
_WORD = re.compile(r"[\w\u0300-\u036f'\u2010-\u2015\u2212-]+")
_CURSES = frozenset({'блять', 'блядь', 'нахуй', 'нахер'})
_EXHAUSTION = {'заебался': 'устал', 'заебалась': 'устала', 'заебались': 'устали'}
_MENTION = re.compile(
    r'(?i)\b(?:слов\w*|фраз\w*|выражени\w*|термин\w*|названи\w*|'
    r'имя|имени|заголов\w*|букваль\w*|дослов\w*|означа\w*|цитат\w*|значени\w*|'
    r'междомети\w*|существительн\w*|склонени\w*|выража\w*)\b')
_LITERAL_COMMAND = re.compile(r'(?i)\b(?:напиши|напечатай|произнеси|скажи|вставь)\b[^.!?;\r\n]{0,80}\b(?:блять|блядь|нахуй|нахер|сука|заебался|заебалась|заебались)\b')
_LITERAL_OBJECT = re.compile(r'(?i)\b(?:убира\w*|убор\w*|смыва\w*|запах\w*|фекал\w*|экскрем\w*|анализ\w*|щен\w*|собак\w*)\b')
_TECH = re.compile(r'\S*(?:[/\\`]|--|[\w-]+\.[\w-]+|[\w-]+=[\w-]+)\S*')


def quoted_ranges(source):
    """Nested straight/curly quotes and code; malformed scopes disable all edits."""
    pairs = {'«': '»', '‹': '›', '“': '”', '„': '“', '‘': '’', '‚': '‘',
             '"': '"', "'": "'", '`': '`'}
    stack, ranges = [], []
    for index, char in enumerate(source):
        # An apostrophe inside an identifier is not the start of a quotation.
        if char in {"'", '’'} and 0 < index < len(source) - 1 and source[index - 1].isalnum() and source[index + 1].isalnum():
            continue
        if stack and char == stack[-1][0]:
            _, start = stack.pop()
            ranges.append((start, index + 1))
        elif char in pairs:
            stack.append((pairs[char], index))
        elif char in {'»', '›', '”', '’'}:
            return None
    if stack:
        return None
    # Repeated identical straight delimiters cannot encode nesting reliably.
    # Over-shield their envelope rather than expose a possibly nested word.
    for char in ('"', "'", '`'):
        positions = [i for i, value in enumerate(source) if value == char]
        if len(positions) > 2:
            ranges.append((positions[0], positions[-1] + 1))
    return ranges


def _clause(source, start, end):
    left = max((source.rfind(mark, 0, start) for mark in '.!?;\r\n'), default=-1) + 1
    right = min((pos for mark in '.!?;\r\n' if (pos := source.find(mark, end)) >= 0), default=len(source))
    return source[left:right], source[left:start]


def _inventory(source):
    quotes = quoted_ranges(source)
    if quotes is None:
        return []
    shields = quotes + [m.span() for m in _TECH.finditer(source)]
    shields += [m.span() for m in re.finditer(r'(?m)^[ \t]*>[^\r\n]*', source)]
    deletions, replacements = [], []
    for match in _WORD.finditer(source):
        start, end = match.span()
        if any(start < right and end > left for left, right in shields):
            continue
        clause, prefix = _clause(source, start, end)
        if _MENTION.search(clause) or _LITERAL_COMMAND.search(clause):
            continue
        word = match.group().lower()
        before, after = source[:start], source[end:]
        comma_left = re.search(r',[ \t]*$', before)
        comma_right = re.match(r'[ \t]*,', after)
        # Bare nouns and negated predicates are not interjections. Comma- or
        # sentence-opening use is the supported channel, not arbitrary roots.
        isolated = comma_left or (not prefix.strip() and comma_right)
        if word == 'блядь' and re.match(r'(?i)[ \t]*,[ \t]*(?:котор\w*|что|чья)\b', after):
            continue
        if re.search(r'(?i)\b(?:не|ни)[ \t]+$', prefix):
            continue
        curse_tail = word == 'сука' and comma_left and not re.match(r'[ \t]*[\w]', after)
        if (word in _CURSES and isolated) or curse_tail:
            if word == 'сука' and _LITERAL_OBJECT.search(clause):
                continue
            # Standalone exclamations need sentence-level interpretation. Preserve
            # their punctuation rather than attach an orphan ! to the next task.
            if not prefix.strip() and re.match(r'[ \t]*[.!?;]', after):
                continue
            deletions.append((start, end))
        elif word in {'ох', 'ах'} and not prefix.strip() and comma_right:
            deletions.append((start, end))
        elif word in _EXHAUSTION:
            if (re.search(r'(?i)\b(?:я|мы)(?:[ \t]+уже)?[ \t]+$', prefix)
                    and not re.search(r'(?i)\b(?:не|если|когда|ли)\b', clause)):
                neutral = _EXHAUSTION[word]
                if match.group()[0].isupper():
                    neutral = neutral.capitalize()
                replacements.append((start, end, neutral))
        elif word == 'говно' and re.search(r'(?i)\bэто[ \t]+$', prefix):
            # Keep the demonstrative object and the exhaustion predicate/action.
            # Ambiguous literal uses abstain; this is not a generic noun blacklist.
            if (re.search(r'(?i)\b(?:я|мы)(?:[ \t]+уже)?[ \t]+заебал(?:ся|ась|ись),?[ \t]+это[ \t]+$', prefix)
                    and re.match(r'(?i)[ \t]+[а-яё]+(?:ть|ти)\b', after)
                    and not re.search(r'(?i)\b(?:не|если|когда|ли)\b', clause)
                    and not _LITERAL_OBJECT.search(clause)):
                deletions.append((start, end))

    # Merge adjacent curse runs before attaching only their local separators.
    runs = []
    for start, end in deletions:
        if runs and re.fullmatch(r'[ ,\t]+', source[runs[-1][1]:start]):
            runs[-1] = (runs[-1][0], end)
        else:
            runs.append((start, end))
    edits = []
    for start, end in runs:
        left = re.search(r',[ \t]*$', source[:start])
        right = re.match(r'[ \t]*,[ \t]*', source[end:])
        if left:
            start = left.start()
        if right:
            end += right.end()
            # A model may remove either comma around an interposed filler.
            # Keep one original separator: it may belong to a conditional clause.
            replacement = ', ' if left else ''
            alternatives = (', ', ' ') if left else (replacement,)
        elif left:
            replacement, alternatives = '', ('',)
        else:
            space = re.match(r'[ \t]+', source[end:])
            if space:
                end += space.end()
            replacement, alternatives = '', ('',)
        edits.append((start, end, replacement, alternatives))
    edits += [(start, end, value, ()) for start, end, value in replacements]
    edits.sort()
    if any(a[1] > b[0] for a, b in zip(edits, edits[1:])):
        return []
    return edits


def render_supported_cleanup(source, candidate):
    """Validate source-anchored model edits, then render supported local edits.

    Prefix-position sets avoid exponential regex backtracking with repeated spans.
    Fixed slices preserve punctuation scope, quotes, whitespace and occurrences.
    Only capitalization of the first remaining letter after an opening deletion
    may vary in the model reply; output still copies that letter from the source.
    """
    edits = _inventory(source)
    pieces, cursor, positions = [], 0, {0}
    opening = False
    for start, end, replacement, alternatives in edits:
        fixed = source[cursor:start]
        positions = _advance(candidate, positions, _fixed_choices(fixed, opening))
        pieces.append(fixed)
        positions = _advance(candidate, positions, (source[start:end], *alternatives))
        pieces.append(replacement)
        opening = bool(not source[:start].strip() and not replacement)
        cursor = end
    fixed = source[cursor:]
    positions = _advance(candidate, positions, _fixed_choices(fixed, opening))
    pieces.append(fixed)
    if len(candidate) not in positions:
        raise ValueError('unsupported_model_edit')
    result = ''.join(pieces)
    if not re.search(r'\w', result):
        raise ValueError('empty_supported_edit')
    return result


def _advance(candidate, positions, choices):
    return {pos + len(value) for pos in positions for value in choices if candidate.startswith(value, pos)}


def _fixed_choices(text, opening):
    if opening:
        first = re.search(r'[^\W\d_]', text)
        if first:
            i = first.start()
            return (text, text[:i] + text[i].swapcase() + text[i + 1:])
    return (text,)
