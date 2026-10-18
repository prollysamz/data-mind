"""Unit tests for DuckDBAdapter."""

from pathlib import Path
import duckdb
import pytest

from datamind.adapters.duckdb_adapter import DuckDBAdapter


def test_duckdb_in_memory():
    with DuckDBAdapter(":memory:") as adapter:
        assert adapter.dialect == "duckdb"
        adapter.conn.execute("CREATE TABLE test_tbl (id INT, val VARCHAR)")
        adapter.conn.execute("INSERT INTO test_tbl VALUES (1, 'alpha'), (2, 'beta')")

        tables = adapter.list_tables()
        assert "test_tbl" in tables

        desc = adapter.describe_table("test_tbl")
        col_names = [d["name"] for d in desc]
        assert "id" in col_names
        assert "val" in col_names

        res = adapter.execute("SELECT * FROM test_tbl ORDER BY id")
        assert res.columns == ["id", "val"]
        assert res.rows == [(1, "alpha"), (2, "beta")]
        assert res.query_id is not None
        assert not res.truncated
        assert res.elapsed_ms >= 0


def test_duckdb_truncation():
    with DuckDBAdapter(":memory:", max_rows=3) as adapter:
        adapter.conn.execute("CREATE TABLE large_tbl AS SELECT range AS n FROM range(10)")
        res = adapter.execute("SELECT * FROM large_tbl")
        assert len(res.rows) == 3
        assert res.truncated is True


def test_duckdb_metadata_methods_quote_table_names():
    with DuckDBAdapter(":memory:") as adapter:
        adapter.conn.execute("CREATE TABLE safe_table (id INT)")

        with pytest.raises(duckdb.Error):
            adapter.sample_rows("safe_table; CREATE TABLE injected(id INT); --")

        assert adapter.list_tables() == ["safe_table"]


def test_duckdb_read_only_demo_db():
    demo_db_path = Path("examples/primary/demo.duckdb")
    assert demo_db_path.exists(), "demo.duckdb should exist from build_demo_data"

    with DuckDBAdapter(demo_db_path, read_only=True) as adapter:
        tables = adapter.list_tables()
        assert "PRODUCTS" in tables
        assert "SALES" in tables
        assert "SUPPORT_TICKETS" in tables

        sample = adapter.sample_rows("PRODUCTS", n=2)
        assert len(sample.rows) == 2

        # Verify read-only enforcement
        with pytest.raises(duckdb.Error):
            adapter.execute("INSERT INTO PRODUCTS VALUES (999, 'Malicious', 'Test', 0.0)")
