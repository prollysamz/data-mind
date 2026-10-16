"""Database adapters for DataMind."""

from datamind.adapters.base import DBAdapter, QueryResult
from datamind.adapters.duckdb_adapter import DuckDBAdapter
from datamind.adapters.snowflake_adapter import SnowflakeAdapter

__all__ = ["DBAdapter", "DuckDBAdapter", "QueryResult", "SnowflakeAdapter"]
