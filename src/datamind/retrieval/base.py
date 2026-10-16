"""Document retrieval protocol and Chunk dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Chunk:
    """A retrieved document chunk with provenance ID."""
    chunk_id: str            # "D:<doc_name>:<source_primary_key>"
    doc_name: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0


class Retriever(Protocol):
    """Protocol for document search engines."""
    def build_index(self) -> None:
        """Build or refresh search index."""
        ...

    def search(self, query: str, k: int, filters: dict[str, Any] | None = None) -> list[Chunk]:
        """Search top-k chunks matching query with optional metadata filters."""
        ...
