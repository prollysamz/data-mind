"""Database adapters for DataMind."""

from datamind.adapters.base import DBAdapter, QueryResult
from datamind.adapters.duckdb_adapter import DuckDBAdapter
from datamind.adapters.snowflake_adapter import SnowflakeAdapter

__all__ = ["DBAdapter", "DuckDBAdapter", "QueryResult", "SnowflakeAdapter", "backend_label", "build_adapter"]


def build_adapter(config, backend: str | None = None) -> DBAdapter:
    """Create the read-only adapter selected by ``backend`` or ``config.backend.type``."""
    backend_type = backend or config.backend.type
    if backend_type == "duckdb":
        return DuckDBAdapter(
            db_path=config.backend.duckdb_path,
            read_only=True,
            max_rows=config.guardrails.max_rows,
        )
    if backend_type == "snowflake":
        return SnowflakeAdapter(
            config=config.backend.snowflake,
            max_rows=config.guardrails.max_rows,
            timeout_seconds=config.guardrails.statement_timeout_seconds,
        )
    raise ValueError(f"Unknown database backend: {backend_type}")


def backend_label(config, backend: str | None = None) -> str:
    """Human-readable description of where queries run, for result provenance."""
    backend_type = backend or config.backend.type
    if backend_type == "snowflake":
        sf = config.backend.snowflake
        return f"Snowflake ({sf.database}.{sf.schema}, warehouse {sf.warehouse}, role {sf.role})"
    return f"DuckDB ({config.backend.duckdb_path})"
