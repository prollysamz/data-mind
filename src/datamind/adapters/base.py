"""Database adapter protocol and core query result models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class QueryResult:
    """Standard container for query execution results."""
    columns: list[str]
    rows: list[tuple[Any, ...]]
    query_id: str            # Snowflake: cursor.sfqid; DuckDB: generated uuid
    elapsed_ms: float
    truncated: bool          # True if the row limit cut the result


class DBAdapter(Protocol):
    """Protocol that all database backends (DuckDB, Snowflake) must implement."""
    dialect: str             # "snowflake" | "duckdb" (sqlglot dialect names)

    def execute(self, sql: str) -> QueryResult:
        """Execute query safely and return QueryResult."""
        ...

    def explain(self, sql: str) -> dict[str, Any]:
        """Return backend-specific plan summary."""
        ...

    def list_tables(self) -> list[str]:
        """List accessible tables in active schema."""
        ...

    def describe_table(self, table: str) -> list[dict[str, Any]]:
        """Return column metadata: name, type, nullable."""
        ...

    def sample_rows(self, table: str, n: int = 5) -> QueryResult:
        """Fetch sample rows from table."""
        ...
