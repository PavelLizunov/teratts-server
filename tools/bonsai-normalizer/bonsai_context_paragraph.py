"""Isolated context-visible inventory; the original insertion plan stays local."""
from __future__ import annotations

import json

from bonsai_paragraph_structurer import (
    BonsaiParagraphStructurer, PARAGRAPH_PROMPT, paragraph_boundaries,
)


def context_candidates(source: str) -> list[dict[str, int | str]]:
    """Expose exact adjacent source slices, not character offsets or summaries."""
    boundaries = paragraph_boundaries(source)
    offsets = [0, *[item['offset'] for item in boundaries], len(source)]
    return [dict(id=item['id'], before=source[offsets[i]:offsets[i + 1]],
                 after=source[offsets[i + 1]:offsets[i + 2]])
            for i, item in enumerate(boundaries)]


class BonsaiContextParagraphStructurer(BonsaiParagraphStructurer):
    """Change only model-facing evidence; never selected by the gateway factory."""

    def _messages_for_source(self, source_text: str) -> list[dict[str, str]]:
        content = json.dumps({'source': source_text,
                              'candidates': context_candidates(source_text)}, ensure_ascii=False)
        if len(PARAGRAPH_PROMPT) + len(content) > 20000:
            raise ValueError('paragraph_plan_too_large')
        return [{'role': 'system', 'content': PARAGRAPH_PROMPT},
                {'role': 'user', 'content': content}]
