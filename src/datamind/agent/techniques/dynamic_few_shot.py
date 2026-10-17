"""Dynamic few-shot retrieval technique for small models.

Retrieves top-k most relevant verified example queries from the training library
matching user question keywords, rather than supplying a static prompt list.
"""

from __future__ import annotations

import re
from typing import Any
from datamind.semantic.model import VerifiedQuery


def retrieve_dynamic_few_shot(
    verified_queries: list[VerifiedQuery],
    question: str,
    k: int = 3,
) -> list[VerifiedQuery]:
    """Rank verified queries by token overlap with question and return top-k."""
    if not verified_queries:
        return []

    q_tokens = set(re.findall(r"\b[a-z0-9_]+\b", question.lower()))

    scored: list[tuple[float, VerifiedQuery]] = []
    for vq in verified_queries:
        v_tokens = set(re.findall(r"\b[a-z0-9_]+\b", vq.question.lower()))
        overlap = len(q_tokens & v_tokens)
        scored.append((float(overlap), vq))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [vq for _, vq in scored[:k]]
