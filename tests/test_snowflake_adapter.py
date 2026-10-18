"""Unit tests for SnowflakeAdapter using mocked cursor/connection."""

from unittest.mock import MagicMock, patch

from datamind.adapters.snowflake_adapter import SnowflakeAdapter
from datamind.config import SnowflakeConfig


def test_snowflake_adapter_execute():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    mock_cur.sfqid = "01c7c621-000e-13f1-0000-0002b4e64215"
    mock_cur.description = [("PRODUCT_NAME",), ("REVENUE",)]
    mock_cur.fetchmany.return_value = [("Novaship", 53803.23), ("CloudSync", 12000.0)]

    adapter = SnowflakeAdapter(connection=mock_conn, max_rows=10)
    assert adapter.dialect == "snowflake"

    res = adapter.execute("SELECT PRODUCT_NAME, REVENUE FROM SALES")
    assert res.columns == ["PRODUCT_NAME", "REVENUE"]
    assert len(res.rows) == 2
    assert res.rows[0] == ("Novaship", 53803.23)
    assert res.query_id == "01c7c621-000e-13f1-0000-0002b4e64215"
    assert not res.truncated
    assert res.elapsed_ms >= 0


def test_snowflake_adapter_truncation():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    mock_cur.sfqid = "qid-trunc"
    mock_cur.description = [("ID",)]
    # Return max_rows + 1 items to trigger truncation detection
    mock_cur.fetchmany.return_value = [(1,), (2,), (3,)]

    adapter = SnowflakeAdapter(connection=mock_conn, max_rows=2)
    res = adapter.execute("SELECT ID FROM LARGE_TABLE")
    assert len(res.rows) == 2
    assert res.truncated is True


def test_snowflake_metadata_methods_quote_table_names():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_cur.description = [("ID",)]
    mock_cur.fetchmany.return_value = []

    adapter = SnowflakeAdapter(connection=mock_conn, max_rows=10)
    adapter.sample_rows('SALES"; DROP TABLE USERS; --', n=100)

    executed_sql = mock_cur.execute.call_args.args[0]
    assert executed_sql == 'SELECT * FROM "SALES""; DROP TABLE USERS; --" LIMIT 10'


def test_snowflake_adapter_describe_and_list():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    mock_cur.fetchall.return_value = [
        ("created_on", "SALES", "database", "schema", "TABLE"),
        ("created_on", "PRODUCTS", "database", "schema", "TABLE"),
    ]

    adapter = SnowflakeAdapter(connection=mock_conn)
    tables = adapter.list_tables()
    assert tables == ["PRODUCTS", "SALES"]

    mock_cur.fetchall.return_value = [
        ("ORDER_ID", "NUMBER(38,0)", "COLUMN", "N", None, "Y", "N", None),
        ("AMOUNT", "FLOAT", "COLUMN", "Y", None, "N", "N", None),
    ]
    meta = adapter.describe_table("SALES")
    assert len(meta) == 2
    assert meta[0]["name"] == "ORDER_ID"
    assert meta[0]["nullable"] is False
    assert meta[1]["name"] == "AMOUNT"
    assert meta[1]["nullable"] is True


def test_snowflake_adapter_resolves_config_and_environment(monkeypatch):
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "test-account")
    monkeypatch.setenv("SNOWFLAKE_USER", "test-user")
    monkeypatch.setenv("SNOWFLAKE_PASSWORD", "test-password")
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "ENV_DB")
    monkeypatch.setenv("SNOWFLAKE_SCHEMA", "ENV_SCHEMA")

    mock_conn = MagicMock()
    with patch("snowflake.connector.connect", return_value=mock_conn) as connect:
        adapter = SnowflakeAdapter(
            config=SnowflakeConfig(role="CUSTOM_READONLY", warehouse="CUSTOM_XS"),
        )

    connect.assert_called_once_with(
        account="test-account",
        user="test-user",
        password="test-password",  # pragma: allowlist secret -- mock test value
        role="CUSTOM_READONLY",
        warehouse="CUSTOM_XS",
        database="ENV_DB",
        schema="ENV_SCHEMA",
        network_timeout=30,
    )
    mock_conn.cursor.return_value.execute.assert_called_once_with("USE SECONDARY ROLES NONE")
    adapter.close()
