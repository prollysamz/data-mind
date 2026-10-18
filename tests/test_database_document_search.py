"""Real local SQL execution verifies routing/evidence, not live Snowflake compliance."""

import json

import pytest

from datamind.adapters.duckdb_adapter import DuckDBAdapter
from datamind.agent.evidence import EvidenceStore
from datamind.agent.orchestrator import AgentOrchestrator
from datamind.agent.tools import execute_database_search_tool, execute_sql_tool
from datamind.config import AgentConfig
from datamind.guardrails.sql_guard import SQLGuard
from datamind.semantic.model import ColumnDef, SemanticModel, TableDef


@pytest.fixture
def database(tmp_path):
    adapter = DuckDBAdapter(tmp_path / "documents.duckdb", read_only=False)
    adapter.execute("CREATE TABLE notes (id INTEGER, body VARCHAR)")
    adapter.execute("INSERT INTO notes VALUES (1, 'delivery delayed'), (2, NULL)")
    model = SemanticModel(tables=[TableDef(
        name="notes", primary_key=["id"],
        columns=[ColumnDef(name="id", type="INTEGER"), ColumnDef(name="body", type="VARCHAR")],
    )])
    yield adapter, model
    adapter.close()


def search(adapter, model, store, query="delivery"):
    return execute_database_search_tool(
        query, 5, SQLGuard({"notes"}, dialect=adapter.dialect), adapter, model, store,
    )


def test_search_records_live_rows_and_follows_database_changes(database):
    adapter, model = database
    store = EvidenceStore()
    output = search(adapter, model, store)
    assert "[[Q1:R1]]" in output and "delivery delayed" in output
    assert store.queries[0].result.query_id
    assert "SELECT" in store.queries[0].sql
    adapter.execute("UPDATE notes SET body = 'delivery resolved' WHERE id = 1")
    store.clear()
    output = search(adapter, model, store)
    assert "delivery resolved" in output and "delivery delayed" not in output
    assert store.queries[0].result.rows == [(1, "delivery resolved")]


def test_empty_search_and_null_aggregate_are_distinct(database):
    adapter, model = database
    store = EvidenceStore()
    assert "No rows returned" in search(adapter, model, store, "absent")
    assert store.queries[0].result.rows == []
    execute_sql_tool(
        "SELECT SUM(id) FROM notes WHERE id > 100", "empty aggregate",
        SQLGuard({"notes"}), adapter, store,
    )
    assert store.queries[1].result.rows == [(None,)]


def test_injection_terms_remain_search_literals(database):
    adapter, model = database
    store = EvidenceStore()
    search(adapter, model, store, "missing'; DROP TABLE notes; --")
    assert adapter.execute("SELECT COUNT(*) FROM notes").rows == [(2,)]
    assert store.queries


def test_unsupported_document_schema_runs_no_query(database):
    adapter, _ = database
    model = SemanticModel(tables=[TableDef(name="notes", columns=[ColumnDef(name="id", type="INTEGER")])])
    store = EvidenceStore()
    assert "unsupported" in search(adapter, model, store)
    assert not store.queries


def test_snowflake_dispatch_never_searches_local_index(database):
    adapter, model = database
    # A Snowflake-dialect query executed by a real local SQL engine for a free routing
    # regression test. Its query IDs are DuckDB IDs, never purported Snowflake receipts.
    adapter.dialect = "snowflake"

    class ForbiddenLocalRetriever:
        def search(self, **kwargs):
            raise AssertionError("Snowflake answers must not use the local index")

    class ScriptedModel:
        calls = 0

        def chat(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"tool_calls": [{"id": "search", "function": {
                    "name": "search_documents", "arguments": json.dumps({"query": "delivery"}),
                }}]}
            return {"content": "The delivery was delayed. [[Q1:R1]]"}

    result = AgentOrchestrator(
        ScriptedModel(), adapter, ForbiddenLocalRetriever(), model,
        config=AgentConfig(answerability_check=False),
    ).run("What do the delivery notes say?")
    assert result.success
    assert result.evidence_store.queries[0].result.rows == [(1, "delivery delayed")]
    assert not result.evidence_store.chunks
