"""Snowflake database adapter implementing the DBAdapter protocol."""

from __future__ import annotations

import logging
import time
from typing import Any

from datamind.adapters.base import DBAdapter, QueryResult
from datamind.config import SnowflakeConfig

logger = logging.getLogger(__name__)


class SnowflakeAdapter(DBAdapter):
    """Adapter for Snowflake cloud data warehouse implementing DBAdapter protocol."""

    dialect: str = "snowflake"

    def __init__(
        self,
        config: SnowflakeConfig | None = None,
        *,
        account: str | None = None,
        user: str | None = None,
        password: str | None = None,
        role: str = "DATAMIND_READONLY",
        warehouse: str = "DATAMIND_XS",
        database: str = "DATAMIND",
        schema: str = "PUBLIC",
        max_rows: int = 1000,
        timeout_seconds: float = 30.0,
        connection: Any = None,
    ) -> None:
        self.max_rows = max_rows
        self.timeout_seconds = timeout_seconds

        if connection is not None:
            self._conn = connection
        else:
            try:
                import snowflake.connector
            except ImportError as e:
                raise ImportError(
                    "snowflake-connector-python is required for SnowflakeAdapter. "
                    "Install it via `pip install snowflake-connector-python`."
                ) from e

            cfg = config or SnowflakeConfig()
            acc = account or cfg.get_account()
            usr = user or cfg.get_user()
            pwd = password or cfg.get_password()
            r = role or cfg.role
            wh = warehouse or cfg.warehouse
            db = database or cfg.database or os.getenv("SNOWFLAKE_DATABASE", "DATAMIND")
            sch = schema or cfg.schema or os.getenv("SNOWFLAKE_SCHEMA", "PUBLIC")

            if not acc or not usr or not pwd:
                raise ValueError("Missing Snowflake credentials (account, user, or password).")

            self._conn = snowflake.connector.connect(
                account=acc,
                user=usr,
                password=pwd,
                role=r,
                warehouse=wh,
                database=db or None,
                schema=sch or None,
                network_timeout=int(timeout_seconds),
            )

    def execute(self, sql: str) -> QueryResult:
        """Execute read-only SQL on Snowflake and return normalized QueryResult with real sfqid."""
        t0 = time.perf_counter()
        cur = self._conn.cursor()
        try:
            cur.execute(sql)
            query_id = getattr(cur, "sfqid", "unknown-sfqid") or "unknown-sfqid"
            columns = [desc[0] for desc in cur.description] if cur.description else []

            # Fetch up to max_rows + 1 to detect truncation
            raw_rows = cur.fetchmany(self.max_rows + 1)
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
            cur.close()

    def explain(self, sql: str) -> dict[str, Any]:
        """Fetch Snowflake execution plan."""
        cur = self._conn.cursor()
        try:
            cur.execute(f"EXPLAIN USING TEXT {sql}")
            rows = cur.fetchall()
            plan_str = "\n".join(str(r[0]) for r in rows)
            return {"plan": plan_str}
        finally:
            cur.close()

    def list_tables(self) -> list[str]:
        """List accessible tables in the active schema."""
        cur = self._conn.cursor()
        try:
            cur.execute("SHOW TABLES")
            # In Snowflake SHOW TABLES, name is typically at column index 1
            rows = cur.fetchall()
            return sorted([str(r[1]) for r in rows])
        finally:
            cur.close()

    def describe_table(self, table: str) -> list[dict[str, Any]]:
        """Describe column metadata for table."""
        cur = self._conn.cursor()
        try:
            cur.execute(f"DESCRIBE TABLE {table}")
            rows = cur.fetchall()
            # Snowflake DESCRIBE TABLE: [name, type, kind, null?, default, primary key, unique key, ...]
            meta: list[dict[str, Any]] = []
            for r in rows:
                col_name = str(r[0])
                col_type = str(r[1])
                nullable = str(r[3]).upper() == "Y" if len(r) > 3 else True
                meta.append({
                    "name": col_name,
                    "type": col_type,
                    "nullable": nullable,
                })
            return meta
        finally:
            cur.close()

    def sample_rows(self, table: str, n: int = 5) -> QueryResult:
        """Fetch sample rows from table."""
        return self.execute(f"SELECT * FROM {table} LIMIT {n}")

    def close(self) -> None:
        """Close connection."""
        if hasattr(self, "_conn") and self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass

    def __enter__(self) -> SnowflakeAdapter:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
