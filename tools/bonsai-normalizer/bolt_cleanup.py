"""Finite deletion-only validator for Bolt's actual candidate, never a local editor.

Unsupported changes raise ValueError. Protected scopes and all non-edit source
bytes remain exact; only local separators and capitalization at deletion cuts vary.
This finite inventory is not a general semantic-equivalence classifier.
"""
from __future__ import annotations

import re

_WORD = re.compile(r"[\w\u0300-\u036f'\u2010-\u2015\u2212-]+")
_CURSES = frozenset({'блять', 'блядь', 'нахуй', 'нахер'})
_MENTION = re.compile(
    r'(?i)\b(?:слов\w*|фраз\w*|выражени\w*|термин\w*|названи\w*|'
    r'имя|имени|заголов\w*|букваль\w*|дослов\w*|означа\w*|цитат\w*|значени\w*|'
    r'междомети\w*|существительн\w*|склонени\w*|выража\w*)\b')
_LITERAL_COMMAND = re.compile(
    r'(?i)\b(?:напиши|напечатай|произнеси|скажи|вставь)\b[^.!?;\r\n]{0,80}'
    r'\b(?:блять|блядь|нахуй|нахер|сука|заебался|заебалась|заебались|заебало)\b')
_LITERAL_OBJECT = re.compile(
    r'(?i)\b(?:убира\w*|убор\w*|смыва\w*|запах\w*|фекал\w*|экскрем\w*|анализ\w*|щен\w*|собак\w*)\b')
_TECH = re.compile(r'\S*(?:[/\\`]|--|[\w-]+\.[\w-]+|[\w-]+=[\w-]+)\S*')
_STANDALONE = re.compile(
    r'(?i)^(?:блядь|блять|ёб\s+твою\s+мать|'
    r'(?:меня|нас|всех)(?:\s+(?:уже|это|всё|тоже)){0,3}\s+заебало)$')


def _quoted_ranges(source: str) -> list[tuple[int, int]] | None:
    pairs = {'«': '»', '‹': '›', '“': '”', '„': '”', '‘': '’', '‚': '’',
             '"': '"', "'": "'", '`': '`'}
    stack: list[tuple[str, int]] = []
    ranges: list[tuple[int, int]] = []
    for index, char in enumerate(source):
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
    # Ambiguous repeated straight delimiters shield their complete enclosing span.
    for char in ('"', "'", '`'):
        positions = [i for i, value in enumerate(source) if value == char]
        if len(positions) > 2:
            ranges.append((positions[0], positions[-1] + 1))
    return ranges


def _clause(source: str, start: int, end: int) -> tuple[str, str]:
    left = max(source.rfind(mark, 0, start) for mark in '.!?;\r\n') + 1
    right = min((p for mark in '.!?;\r\n' if (p := source.find(mark, end)) >= 0), default=len(source))
    return source[left:right], source[left:start]


def _protected_ranges(source: str) -> list[tuple[int, int]] | None:
    quotes = _quoted_ranges(source)
    if quotes is None:
        return None
    return (quotes + [m.span() for m in _TECH.finditer(source)]
            + [m.span() for m in re.finditer(r'(?m)^[ \t]*>[^\r\n]*', source)])


def _inventory(source: str) -> list[tuple[int, int, tuple[str, ...], bool]]:
    shields = _protected_ranges(source)
    if shields is None:
        return []

    def shielded(start, end):
        return any(start < right and end > left for left, right in shields)

    # Exact emotional-only sentences, not arbitrary clauses without numbers.
    whole = []
    for match in re.finditer(r'[^.!?;\r\n]+[.!?;]*[ \t]*(?:\r\n|[\r\n])?', source):
        body_match = re.match(r'\s*([^.!?;\r\n]+)', match.group())
        if body_match is None:
            continue
        body = body_match.group(1).strip()
        if _STANDALONE.fullmatch(body) and not shielded(*match.span()):
            start = match.start() + len(match.group()) - len(match.group().lstrip())
            if not source[:start].strip():
                start = 0
            whole.append((start, match.end(), ('',), True))

    deletions = []
    for match in _WORD.finditer(source):
        start, end = match.span()
        if shielded(start, end) or any(start < b and end > a for a, b, _, _ in whole):
            continue
        clause, prefix = _clause(source, start, end)
        if _MENTION.search(clause) or _LITERAL_COMMAND.search(clause):
            continue
        if re.search(r'(?i)\b(?:не|ни)[ \t]+$', prefix):
            continue
        word = match.group().lower()
        left = re.search(r',[ \t]*$', source[:start])
        right = re.match(r'[ \t]*,', source[end:])
        isolated = left or (not prefix.strip() and right)
        if word == 'блядь' and re.match(r'(?i)[ \t]*,[ \t]*(?:котор\w*|что|чья)\b', source[end:]):
            continue
        tail = word == 'сука' and left and not re.match(r'[ \t]*[\w]', source[end:])
        if tail and _LITERAL_OBJECT.search(clause):
            continue
        if (word in _CURSES and isolated) or tail or (word in {'ох', 'ах'} and not prefix.strip() and right):
            deletions.append((start, end, not prefix.strip()))

    runs = []
    for start, end, opening in deletions:
        if runs and re.fullmatch(r'[ ,\t]+', source[runs[-1][1]:start]):
            runs[-1][1] = end
        else:
            runs.append([start, end, opening])
    edits = list(whole)
    for start, end, opening in runs:
        left = re.search(r',[ \t]*$', source[:start])
        right = re.match(r'[ \t]*,[ \t]*', source[end:])
        if left:
            start = left.start()
        if right:
            end += right.end()
            choices = (', ', ' ') if left else ('',)
        else:
            choices = ('',)
        edits.append((start, end, choices, opening))
    edits.sort()
    if any(a[1] > b[0] for a, b in zip(edits, edits[1:])):
        return []
    return edits


def _fixed_choices(text: str, at_cut: bool, offset: int,
                   shields: list[tuple[int, int]]) -> tuple[str, ...]:
    if at_cut:
        first = re.search(r'[^\W\d_]', text)
        if first:
            i = first.start()
            if not any(left <= offset + i < right for left, right in shields):
                return (text, text[:i] + text[i].swapcase() + text[i + 1:])
    return (text,)


def render_supported_bolt_cleanup(source: str, candidate: str) -> str:
    # Track actual candidate choices; keeping a span never enables capitalization edits.
    shields = _protected_ranges(source)
    if shields is None:
        if candidate != source:
            raise ValueError('unsupported_model_edit')
        shields = []
    states = {(0, False)}
    cursor = 0
    for start, end, choices, opening in _inventory(source):
        fixed = source[cursor:start]
        positions = {pos + len(value) for pos, cut in states
                     for value in _fixed_choices(fixed, cut, cursor, shields) if candidate.startswith(value, pos)}
        states = set()
        for pos in positions:
            original = source[start:end]
            if candidate.startswith(original, pos):
                states.add((pos + len(original), False))
            for value in choices:
                if candidate.startswith(value, pos):
                    states.add((pos + len(value), opening))
        if not states:
            raise ValueError('unsupported_model_edit')
        cursor = end
    if not any(candidate[pos:] == value for pos, cut in states
               for value in _fixed_choices(source[cursor:], cut, cursor, shields)):
        raise ValueError('unsupported_model_edit')
    if not re.search(r'\w', candidate):
        raise ValueError('empty_supported_edit')
    return candidate
