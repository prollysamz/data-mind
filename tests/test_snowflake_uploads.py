from unittest.mock import MagicMock, patch

import pytest

from datamind.config import AppConfig, BackendConfig, SnowflakeConfig
from datamind.uploads.manager import UploadError, UploadManager
from datamind.uploads.snowflake_store import SnowflakeUploadStore, session_schema


def configuration():
    return AppConfig(backend=BackendConfig(type="snowflake", snowflake=SnowflakeConfig(database="DATAMIND")))


def test_cloud_upload_does_not_create_local_database_and_uses_readonly_queries(tmp_path):
    manager = UploadManager(base_dir=tmp_path, enabled=True, config=configuration())
    manager.snowflake_store = MagicMock()
    manager.snowflake_store.load_table.side_effect = lambda sid, table, conn, columns, rows: {
        "backend": "snowflake", "rows": conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0],
        "query_id": "test-receipt-not-live", "schema": session_schema(sid),
    }
    session = manager.create_session()
    meta = manager.ingest_file(session, "orders.csv", b"id,amount,private_note\n1,12,private\n2,20,private\n")
    assert meta["storage"]["rows"] == 2
    assert not session.db_path.exists()
    model = manager.confirm_model(session, {"tables": {"orders": {"columns": {"private_note": {"enabled": False}}}}})
    assert model.tables[0].name == "ORDERS"
    assert model.tables[0].column_names() == ["ID", "AMOUNT"]
    with patch("datamind.uploads.manager.SnowflakeAdapter") as adapter:
        adapter.return_value.dialect = "snowflake"
        orchestrator, _, retriever = manager.create_session_orchestrator(session.session_id, configuration())
    cfg = adapter.call_args.kwargs["config"]
    assert cfg.role == "DATAMIND_READONLY"
    assert cfg.schema == session_schema(session.session_id)
    assert retriever is None
    with pytest.raises(ValueError, match="reviewed"):
        orchestrator.sql_guard.validate("SELECT private_note FROM orders")
    assert "PRIVATE_NOTE" not in orchestrator.sql_guard.validate("SELECT * FROM orders")


def test_cloud_failure_never_activates_a_local_fallback_and_cleanup_is_retryable(tmp_path):
    manager = UploadManager(base_dir=tmp_path, enabled=True, config=configuration())
    manager.snowflake_store = MagicMock()
    manager.snowflake_store.load_table.side_effect = RuntimeError("connection failed")
    session = manager.create_session()
    with pytest.raises(UploadError, match="No local dataset"):
        manager.ingest_file(session, "orders.csv", b"id,amount\n1,12\n")
    assert not session.tables_meta and not session.db_path.exists()
    manager.snowflake_store.delete_session.side_effect = RuntimeError("network unavailable")
    with pytest.raises(UploadError, match="retained"):
        manager.delete_session(session.session_id)
    assert session.meta_path.exists()
    manager.snowflake_store.delete_session.side_effect = None
    assert manager.delete_session(session.session_id)


def test_loader_binds_values_and_cleans_up_failed_row_verification(tmp_path):
    import duckdb

    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE notes (body VARCHAR)")
    attack = "'); DROP DATABASE DATAMIND; --"
    conn.execute("INSERT INTO notes VALUES (?)", [attack])
    loader = MagicMock()
    cursor = loader._conn.cursor.return_value
    cursor.fetchone.return_value = (1,)
    cursor.sfqid = "test-receipt"
    store = SnowflakeUploadStore(configuration())
    with patch.object(SnowflakeUploadStore, "_loader", return_value=loader):
        receipt = store.load_table("a" * 12, "notes", conn, [{"name": "body", "inferred_type": "VARCHAR"}], 1)
        assert receipt["rows"] == 1
        statement, values = cursor.executemany.call_args.args
        assert attack not in statement and values == [(attack,)]
        cursor.fetchone.return_value = (0,)
        with pytest.raises(ValueError, match="row count"):
            store.load_table("b" * 12, "notes", conn, [{"name": "body", "inferred_type": "VARCHAR"}], 1)
        assert any("DROP TABLE" in call.args[0] for call in cursor.execute.call_args_list)
    conn.close()


def test_session_schema_rejects_untrusted_identifiers():
    with pytest.raises(ValueError):
        session_schema('anything"; DROP DATABASE DATAMIND')
