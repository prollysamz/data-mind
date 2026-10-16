"""Database adapters for DataMind."""

from datamind.adapters.base import DBAdapter, QueryResult
from datamind.adapters.duckdb_adapter import DuckDBAdapter

__all__ = ["DBAdapter", "DuckDBAdapter", "QueryResult"]
