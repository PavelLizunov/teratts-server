"""Isolated schema-constrained literal selector, not used by the gateway factory."""
from __future__ import annotations

from typing import Any

from bonsai_literal_editor import BonsaiLiteralEditor, candidate_spans


class BonsaiConstrainedLiteralEditor(BonsaiLiteralEditor):
    """Request bounded ID syntax; inherited rendering still enforces ID order/uniqueness."""

    def _response_format_for_source(self, source_text: str) -> dict[str, Any]:
        count = len(candidate_spans(source_text))
        return {'type': 'json_schema', 'json_schema': {
            'name': 'bonsai_literal_selection', 'strict': True,
            'schema': {'type': 'object', 'properties': {'delete': {
                'type': 'array', 'items': {'type': 'integer', 'enum': list(range(count))},
                'maxItems': count}}, 'required': ['delete'], 'additionalProperties': False}}}
