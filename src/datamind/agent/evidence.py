"""Evidence store maintaining stable provenance IDs for queries, rows, and document chunks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from datamind.adapters.base import QueryResult
from datamind.retrieval.base import Chunk


@dataclass
class QueryRecord:
    query_num: int
    query_label: str       # "Q1", "Q2", ...
    sql: str
    purpose: str
    result: QueryResult
    row_ids: list[str] = field(default_factory=list)
    kind: str = "answer"


@dataclass
class EvidenceStore:
    """Store and resolve evidence items (cells, rows, documents) by stable ID."""
    queries: list[QueryRecord] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)
    validation_queries: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    _rows: dict[str, dict[str, Any]] = field(default_factory=dict)
    _chunks_by_id: dict[str, Chunk] = field(default_factory=dict)
    _query_counter: int = 0

    def clear(self) -> None:
        """Reset the evidence store to an empty state."""
        self.queries.clear()
        self.chunks.clear()
        self.validation_queries.clear()
        self.diagnostics.clear()
        self._rows.clear()
        self._chunks_by_id.clear()
        self._query_counter = 0

    def add_query(self, sql: str, purpose: str, result: QueryResult, *, kind: str = "answer") -> str:
        """Add query result to store, assign Q<n>:R<m> IDs to each row, return query label (e.g. 'Q1')."""
        self._query_counter += 1
        query_label = f"Q{self._query_counter}"
        row_ids: list[str] = []

        for row_idx, row_values in enumerate(result.rows, start=1):
            row_id = f"{query_label}:R{row_idx}"
            row_ids.append(row_id)
            # Store column mapping (case-preserved and case-insensitive lookup)
            row_dict: dict[str, Any] = {}
            for col_name, val in zip(result.columns, row_values, strict=False):
                row_dict[col_name] = val
                row_dict[col_name.lower()] = val
                row_dict[col_name.upper()] = val
            self._rows[row_id] = row_dict

        record = QueryRecord(
            query_num=self._query_counter,
            query_label=query_label,
            sql=sql,
            purpose=purpose,
            result=result,
            row_ids=row_ids,
            kind=kind,
        )
        self.queries.append(record)
        return query_label

    def add_chunks(self, search_query: str, chunks: list[Chunk]) -> list[str]:
        """Add retrieved chunks to store, keeping verbatim chunk IDs."""
        added_ids: list[str] = []
        for chunk in chunks:
            self.chunks.append(chunk)
            self._chunks_by_id[chunk.chunk_id] = chunk
            added_ids.append(chunk.chunk_id)
        return added_ids

    def get_cell(self, row_id: str, column: str) -> Any:
        """Get cell value by row ID (e.g. 'Q1:R1') and column name."""
        if row_id not in self._rows:
            raise KeyError(f"Row ID not found in evidence store: {row_id}")
        row = self._rows[row_id]
        if column in row:
            return row[column]
        if column.lower() in row:
            return row[column.lower()]
        if column.upper() in row:
            return row[column.upper()]
        raise KeyError(f"Column '{column}' not found in row '{row_id}'. Available: {list(row.keys())}")

    def get_row(self, row_id: str) -> dict[str, Any]:
        """Get row dictionary by row ID."""
        if row_id not in self._rows:
            raise KeyError(f"Row ID not found in evidence store: {row_id}")
        # Return only unique keys (ignore case variants)
        # Find which query this belongs to
        query_label = row_id.split(":")[0]
        matching_query = next((q for q in self.queries if q.query_label == query_label), None)
        if matching_query:
            cols = matching_query.result.columns
            return {c: self._rows[row_id][c] for c in cols}
        return self._rows[row_id]

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        """Retrieve chunk by its ID."""
        return self._chunks_by_id.get(chunk_id)

    def has_id(self, evidence_id: str) -> bool:
        """Check if an evidence ID (row ID or chunk ID) exists."""
        return (evidence_id in self._rows) or (evidence_id in self._chunks_by_id) or self.get_execution(evidence_id) is not None

    def get_execution(self, evidence_id: str) -> dict[str, Any] | None:
        """Resolve execution metadata separately from database result rows."""
        query = next((q for q in self.queries if evidence_id == f"{q.query_label}:EXEC"), None)
        if query is None:
            return None
        return {"sql": query.sql, "query_id": query.result.query_id,
                "row_count": len(query.result.rows), "truncated": query.result.truncated}

    def to_json(self) -> dict[str, Any]:
        """Serialize evidence store into a JSON-compatible dictionary."""
        return {
            "queries": [
                {
                    "label": q.query_label,
                    "sql": q.sql,
                    "purpose": q.purpose,
                    "query_id": q.result.query_id,
                    "elapsed_ms": q.result.elapsed_ms,
                    "truncated": q.result.truncated,
                    "columns": q.result.columns,
                    "row_count": len(q.result.rows),
                    "row_ids": q.row_ids,
                    "rows": [
                        {
                            "row_id": r_id,
                            "cells": {c: self._rows[r_id][c] for c in q.result.columns},
                        }
                        for r_id in q.row_ids
                    ],
                }
                for q in self.queries
            ],
            "chunks": [
                {
                    "chunk_id": c.chunk_id,
                    "doc_name": c.doc_name,
                    "text": c.text,
                    "metadata": c.metadata,
                    "score": c.score,
                }
                for c in self.chunks
            ],
        }
