"""Contract tests verifying identical interface and semantics for all DBAdapter implementations.

Both DuckDBAdapter and SnowflakeAdapter must pass this exact suite.
"""

from typing import Generator
from unittest.mock import MagicMock
import pytest

from datamind.adapters.base import DBAdapter, QueryResult
from datamind.adapters.duckdb_adapter import DuckDBAdapter
from datamind.adapters.snowflake_adapter import SnowflakeAdapter


def create_mock_snowflake_adapter(max_rows: int = 100) -> SnowflakeAdapter:
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    mock_cur.sfqid = "01c7c621-mock-query-id"
    mock_cur.description = [("ID",), ("VAL",)]
    mock_cur.fetchall.return_value = [
        ("created_on", "USERS", "db", "public", "TABLE"),
        ("created_on", "ORDERS", "db", "public", "TABLE"),
    ]
    mock_cur.fetchmany.return_value = [(1, "item_a"), (2, "item_b")]

    adapter = SnowflakeAdapter(connection=mock_conn, max_rows=max_rows)
    return adapter


@pytest.fixture(params=["duckdb", "snowflake"])
def adapter_instance(request) -> Generator[DBAdapter, None, None]:
    if request.param == "duckdb":
        adapter = DuckDBAdapter(":memory:", max_rows=100)
        adapter.conn.execute("CREATE TABLE orders (id INT, val VARCHAR)")
        adapter.conn.execute("INSERT INTO orders VALUES (1, 'item_a'), (2, 'item_b')")
        adapter.conn.execute("CREATE TABLE users (id INT, name VARCHAR)")
        yield adapter
        adapter.close()
    elif request.param == "snowflake":
        yield create_mock_snowflake_adapter(max_rows=100)


def test_adapter_protocol_compliance(adapter_instance: DBAdapter):
    assert hasattr(adapter_instance, "dialect")
    assert adapter_instance.dialect in ("duckdb", "snowflake")
    assert callable(getattr(adapter_instance, "execute", None))
    assert callable(getattr(adapter_instance, "explain", None))
    assert callable(getattr(adapter_instance, "list_tables", None))
    assert callable(getattr(adapter_instance, "describe_table", None))
    assert callable(getattr(adapter_instance, "sample_rows", None))


def test_adapter_list_tables_contract(adapter_instance: DBAdapter):
    tables = adapter_instance.list_tables()
    assert isinstance(tables, list)
    assert len(tables) >= 2
    for t in tables:
        assert isinstance(t, str)
    upper_tables = [t.upper() for t in tables]
    assert "ORDERS" in upper_tables


def test_adapter_describe_table_contract(adapter_instance: DBAdapter):
    if adapter_instance.dialect == "snowflake":
        # configure mock cursor fetchall for describe
        cur = adapter_instance._conn.cursor.return_value
        cur.fetchall.return_value = [
            ("ID", "NUMBER(38,0)", "COLUMN", "N", None, "Y", "N", None),
            ("VAL", "VARCHAR(16777216)", "COLUMN", "Y", None, "N", "N", None),
        ]

    cols = adapter_instance.describe_table("orders" if adapter_instance.dialect == "duckdb" else "ORDERS")
    assert isinstance(cols, list)
    assert len(cols) >= 2
    for col in cols:
        assert "name" in col
        assert "type" in col
        assert "nullable" in col
        assert isinstance(col["name"], str)
        assert isinstance(col["type"], str)
        assert isinstance(col["nullable"], bool)


def test_adapter_execute_contract(adapter_instance: DBAdapter):
    res = adapter_instance.execute("SELECT id, val FROM orders")
    assert isinstance(res, QueryResult)
    assert isinstance(res.columns, list)
    assert len(res.columns) == 2
    assert [c.upper() for c in res.columns] == ["ID", "VAL"]
    assert isinstance(res.rows, list)
    assert len(res.rows) == 2
    assert isinstance(res.query_id, str)
    assert len(res.query_id) > 0
    assert isinstance(res.elapsed_ms, (int, float))
    assert res.elapsed_ms >= 0
    assert isinstance(res.truncated, bool)
    assert res.truncated is False


def test_adapter_sample_rows_contract(adapter_instance: DBAdapter):
    sample = adapter_instance.sample_rows("orders" if adapter_instance.dialect == "duckdb" else "ORDERS", n=2)
    assert isinstance(sample, QueryResult)
    assert len(sample.rows) <= 2
    assert len(sample.columns) >= 2


def test_adapter_explain_contract(adapter_instance: DBAdapter):
    if adapter_instance.dialect == "snowflake":
        cur = adapter_instance._conn.cursor.return_value
        cur.fetchall.return_value = [("GlobalStats", 1, 100, 1000)]
        cur.description = [("operation",), ("step",), ("rows",), ("bytes",)]

    plan = adapter_instance.explain("SELECT id, val FROM orders")
    assert isinstance(plan, dict)
    assert "dialect" in plan or "raw" in plan or "steps" in plan or "plan" in plan


def test_adapter_truncation_contract():
    # Test duckdb truncation
    duck = DuckDBAdapter(":memory:", max_rows=2)
    duck.conn.execute("CREATE TABLE t AS SELECT range AS n FROM range(10)")
    res_duck = duck.execute("SELECT * FROM t")
    assert len(res_duck.rows) == 2
    assert res_duck.truncated is True
    duck.close()

    # Test snowflake truncation
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_cur.sfqid = "qid-trunc"
    mock_cur.description = [("N",)]
    mock_cur.fetchmany.return_value = [(1,), (2,), (3,)]  # max_rows + 1 triggers truncation
    sf = SnowflakeAdapter(connection=mock_conn, max_rows=2)
    res_sf = sf.execute("SELECT * FROM t")
    assert len(res_sf.rows) == 2
    assert res_sf.truncated is True
