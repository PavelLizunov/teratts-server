"""Extract only representable English timing phrases, not a transcript filter.

Cyrillic/numeric auxiliary words are wildcard separators. Their spelling never
enters either acoustic head. Latin-like unsupported words still fail explicitly.
"""
import unicodedata


def auxiliary_words(text):
    words=[];pending=''
    for char in text:
        if char.isspace() or (unicodedata.category(char)[0] in 'PZS' and char!="'"):
            if pending:words.append(pending);pending=''
        else:pending+=char
    if pending:words.append(pending)
    return words


def english_timing_labels(text, processor, english_case='original'):
    words=auxiliary_words(text)
    if not words:raise ValueError('Empty auxiliary proposal')
    sequence=[];provenance=[]
    for word in words:
        normalized=word.lower() if english_case=='lower' else word
        ids=processor.encode(normalized)
        en_ok=bool(ids) and 0 not in ids and processor.decode(ids)==normalized
        cyrillic=any('CYRILLIC' in unicodedata.name(c,'') for c in word)
        gap_ok=all('CYRILLIC' in unicodedata.name(c,'') or c.isdecimal() or unicodedata.category(c).startswith('M') or c=="'" for c in word)
        if gap_ok and (cyrillic or any(c.isdecimal() for c in word)):
            sequence.append(('rus',None))
            provenance.append({'original':word,'role':'wildcard_gap','acoustic_token_ids':None})
        elif en_ok and not cyrillic:
            if not processor.id_to_piece(ids[0]).startswith('▁'):raise ValueError('English word lacks published start marker')
            sequence.extend(('eng',token) for token in ids)
            provenance.append({'original':word,'role':'english_timing','english_token_ids':ids})
        else:
            raise ValueError('Unsupported auxiliary English/non-Cyrillic word: '+word)
    return sequence,provenance
