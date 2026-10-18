"""DuckDB database adapter implementing DBAdapter protocol."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

import duckdb

from datamind.adapters.base import DBAdapter, QueryResult


def _quote_identifier_path(identifier: str) -> str:
    """Quote each component of a potentially qualified SQL identifier."""
    parts = identifier.split(".")
    if not parts or any(not part for part in parts):
        raise ValueError("Table identifier must not be empty")
    return ".".join('"' + part.replace('"', '""') + '"' for part in parts)


class DuckDBAdapter(DBAdapter):
    """Adapter for local DuckDB database."""

    dialect: str = "duckdb"

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        read_only: bool = True,
        max_rows: int = 1000,
    ) -> None:
        self.db_path = str(db_path)
        self.max_rows = max_rows
        is_memory = self.db_path == ":memory:"
        self.read_only = False if is_memory else read_only

        # Connect to DuckDB
        self.conn = duckdb.connect(database=self.db_path, read_only=self.read_only)

    def execute(self, sql: str) -> QueryResult:
        """Execute query safely and return normalized QueryResult."""
        t0 = time.perf_counter()
        query_id = str(uuid.uuid4())

        cursor = self.conn.cursor()
        try:
            rel = cursor.execute(sql)
            columns = [desc[0] for desc in rel.description] if rel.description else []
            # Fetch max_rows + 1 to detect truncation
            raw_rows = rel.fetchmany(self.max_rows + 1)
            truncated = len(raw_rows) > self.max_rows
            final_rows = [tuple(r) for r in raw_rows[: self.max_rows]]
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            return QueryResult(
                columns=columns,
                rows=final_rows,
                query_id=query_id,
                elapsed_ms=round(elapsed_ms, 2),
                truncated=truncated,
            )
        finally:
            cursor.close()

    def explain(self, sql: str) -> dict[str, Any]:
        """Return backend-specific plan summary."""
        res = self.conn.execute(f"EXPLAIN {sql}").fetchall()
        plan_str = "\n".join(str(r[1]) if len(r) > 1 else str(r[0]) for r in res)
        return {"plan": plan_str}

    def list_tables(self) -> list[str]:
        """List accessible tables in active schema."""
        res = self.conn.execute("SHOW TABLES").fetchall()
        return sorted([str(r[0]) for r in res])

    def describe_table(self, table: str) -> list[dict[str, Any]]:
        """Return column metadata: name, type, nullable."""
        res = self.conn.execute(f"DESCRIBE {_quote_identifier_path(table)}").fetchall()
        columns_meta: list[dict[str, Any]] = []
        for r in res:
            # DuckDB DESCRIBE returns: column_name, column_type, null, key, default, extra
            col_name = str(r[0])
            col_type = str(r[1])
            nullable = str(r[2]).upper() == "YES" if len(r) > 2 else True
            columns_meta.append({
                "name": col_name,
                "type": col_type,
                "nullable": nullable,
            })
        return columns_meta

    def sample_rows(self, table: str, n: int = 5) -> QueryResult:
        """Fetch sample rows from table."""
        safe_limit = max(0, min(int(n), self.max_rows))
        return self.execute(f"SELECT * FROM {_quote_identifier_path(table)} LIMIT {safe_limit}")

    def close(self) -> None:
        """Close connection."""
        if hasattr(self, "conn") and self.conn is not None:
            self.conn.close()

    def __enter__(self) -> DuckDBAdapter:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
