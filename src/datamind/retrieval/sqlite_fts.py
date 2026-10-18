"""SQLite FTS5 Document Retriever implementation with stable chunk IDs."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

import duckdb

from datamind.retrieval.base import Chunk, Retriever

logger = logging.getLogger(__name__)


class SQLiteFTSRetriever(Retriever):
    """Document retriever using SQLite FTS5 for full-text BM25 search."""

    def __init__(
        self,
        index_path: str | Path = ":memory:",
        source_db_path: str | Path | None = None,
    ) -> None:
        self.index_path = str(index_path)
        self.source_db_path = str(source_db_path) if source_db_path else None

        if self.index_path != ":memory:":
            Path(self.index_path).parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(self.index_path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize SQLite FTS5 tables and metadata store."""
        cur = self.conn.cursor()
        cur.execute("PRAGMA journal_mode = WAL;")
        cur.execute("PRAGMA synchronous = NORMAL;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS documents_meta (
                chunk_id TEXT PRIMARY KEY,
                doc_name TEXT NOT NULL,
                source_pk TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            );
        """)
        cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                chunk_id UNINDEXED,
                doc_name UNINDEXED,
                content,
                tokenize = 'unicode61'
            );
        """)
        self.conn.commit()

    def index_document(
        self,
        doc_name: str,
        source_pk: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> str:
        """Index a single document and return its stable chunk ID (D:<doc_name>:<source_pk>)."""
        chunk_id = f"D:{doc_name}:{source_pk}"
        meta = metadata or {}
        meta_json = json.dumps(meta, default=str)

        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO documents_meta (chunk_id, doc_name, source_pk, metadata_json)
            VALUES (?, ?, ?, ?)
            """,
            (chunk_id, doc_name, source_pk, meta_json),
        )
        cur.execute(
            """
            DELETE FROM documents_fts WHERE chunk_id = ?
            """,
            (chunk_id,),
        )
        cur.execute(
            """
            INSERT INTO documents_fts (chunk_id, doc_name, content)
            VALUES (?, ?, ?)
            """,
            (chunk_id, doc_name, content),
        )
        if commit:
            self.conn.commit()
        return chunk_id

    def build_index(self, force: bool = False) -> None:
        """Ingest and index documents from source database (SUPPORT_TICKETS / OLIST_ORDER_REVIEWS)."""
        if not self.source_db_path:
            return
        if not Path(self.source_db_path).exists():
            logger.warning(
                "Document index source '%s' not found; document search will return no results.",
                self.source_db_path,
            )
            return

        cur = self.conn.cursor()
        cur.execute("SELECT count(*) FROM documents_meta")
        if not force and cur.fetchone()[0] > 0:
            return

        duck_conn = duckdb.connect(self.source_db_path, read_only=True)
        try:
            existing_tables = [r[0].upper() for r in duck_conn.execute("SHOW TABLES").fetchall()]
            if "SUPPORT_TICKETS" in existing_tables:
                tickets = duck_conn.execute("""
                    SELECT ticket_id, created_at, product_name, category, priority, body
                    FROM SUPPORT_TICKETS
                    ORDER BY ticket_id
                """).fetchall()

                for tid, created, prod, cat, prio, body in tickets:
                    content = (
                        f"Ticket {tid} (Date: {created})\n"
                        f"Product: {prod}\n"
                        f"Category: {cat} | Priority: {prio}\n"
                        f"Details: {body}"
                    )
                    meta = {
                        "ticket_id": str(tid),
                        "created_at": str(created),
                        "product_name": str(prod),
                        "category": str(cat),
                        "priority": str(prio),
                    }
                    self.index_document(
                        doc_name="SUPPORT_TICKETS",
                        source_pk=str(tid),
                        content=content,
                        metadata=meta,
                        commit=False,
                    )
                self.conn.commit()

            if "OLIST_ORDER_REVIEWS" in existing_tables:
                reviews = duck_conn.execute("""
                    SELECT review_id, order_id, review_score, review_comment_title, review_comment_message, review_creation_date
                    FROM olist_order_reviews
                    WHERE review_comment_message IS NOT NULL AND length(trim(review_comment_message)) > 0
                """).fetchall()

                for rid, oid, score, title, msg, dt in reviews:
                    content_parts = []
                    if title and title.strip():
                        content_parts.append(title.strip())
                    if msg and msg.strip():
                        content_parts.append(msg.strip())
                    full_content = "\n".join(content_parts)
                    meta = {
                        "review_id": str(rid),
                        "order_id": str(oid),
                        "review_score": int(score) if score is not None else None,
                        "review_creation_date": str(dt),
                    }
                    self.index_document(
                        doc_name="order_reviews",
                        source_pk=str(rid),
                        content=full_content,
                        metadata=meta,
                        commit=False,
                    )
                self.conn.commit()
        finally:
            duck_conn.close()

    def search(
        self,
        query: str,
        k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[Chunk]:
        """Full-text BM25 search over indexed document chunks."""
        words = re.findall(r"\w+", query)
        if not words:
            return []

        # Build clean FTS5 match expression: ("term1" OR "term2")
        match_terms = " OR ".join(f'"{w}"' for w in words if len(w) > 1)
        if not match_terms:
            match_terms = f'"{words[0]}"'

        cur = self.conn.cursor()
        try:
            rows = cur.execute(
                """
                SELECT
                    f.chunk_id,
                    f.doc_name,
                    f.content,
                    bm25(documents_fts) AS rank,
                    m.metadata_json
                FROM documents_fts f
                JOIN documents_meta m ON f.chunk_id = m.chunk_id
                WHERE documents_fts MATCH ?
                ORDER BY rank ASC
                LIMIT ?
                """,
                (match_terms, k * 2),  # Fetch extra to apply post-filters
            ).fetchall()
        except sqlite3.OperationalError:
            # Fallback if query syntax fails
            return []

        results: list[Chunk] = []
        for cid, doc_name, text, rank, meta_json in rows:
            meta = json.loads(meta_json) if meta_json else {}

            # Apply metadata filters if provided
            if filters:
                match_filter = True
                for fk, fv in filters.items():
                    if str(meta.get(fk, "")).lower() != str(fv).lower():
                        match_filter = False
                        break
                if not match_filter:
                    continue

            # SQLite bm25 returns negative numbers where more negative = better match
            # Invert to positive relevance score
            score = -float(rank)

            results.append(
                Chunk(
                    chunk_id=cid,
                    doc_name=doc_name,
                    text=text,
                    metadata=meta,
                    score=score,
                )
            )
            if len(results) >= k:
                break

        return results

    def close(self) -> None:
        if hasattr(self, "conn") and self.conn:
            self.conn.close()
