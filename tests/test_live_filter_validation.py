"""Use a real SQL engine to distinguish invalid codes from measured zero."""

import json

import pytest

from datamind.adapters.duckdb_adapter import DuckDBAdapter
from datamind.agent.evidence import EvidenceStore
from datamind.agent.orchestrator import AgentOrchestrator, requires_structured_sql
from datamind.agent.tools import execute_sql_tool
from datamind.config import AgentConfig
from datamind.guardrails.sql_guard import SQLGuard
from datamind.semantic.model import ColumnDef, SemanticModel, TableDef


@pytest.fixture
def database():
    adapter = DuckDBAdapter()
    conn = adapter.conn
    conn.execute("CREATE TABLE tasks (severity VARCHAR, cost INTEGER)")
    conn.execute("INSERT INTO tasks VALUES ('01-Critical', 10), ('02-Normal', 20), ('01-Critical', 5)")
    model = SemanticModel(tables=[TableDef(name="tasks", columns=[ColumnDef(name="severity", type="VARCHAR"), ColumnDef(name="cost", type="INTEGER")])])
    yield adapter, model
    adapter.close()


def execute(database, sql):
    adapter, model = database
    evidence = EvidenceStore()
    out = execute_sql_tool(sql, "Test aggregate", SQLGuard({"tasks"}), adapter, evidence, model)
    return out, evidence


def test_unique_live_code_is_normalized_and_disclosed_without_false_zero(database):
    out, evidence = execute(database, "SELECT COUNT(*) FROM tasks t WHERE t.severity = 'Critical'")
    assert "Filter assumptions" in out and "01-Critical" in out
    assert evidence.queries[0].result.rows == [(2,)]
    assert "'01-Critical'" in evidence.queries[0].sql
    assert len(evidence.validation_queries) == 2
    assert evidence.validation_queries[0]["query_id"]


def test_ambiguous_codes_require_clarification(database):
    database[0].execute("INSERT INTO tasks VALUES ('03-Critical', 2)")
    out, evidence = execute(database, "SELECT COUNT(*) FROM tasks WHERE severity = 'Critical'")
    assert json.loads(out)["error"] == "InvalidCategoricalFilter"
    assert not evidence.queries


def test_valid_code_and_real_zero_are_accepted(database):
    out, evidence = execute(database, "SELECT COUNT(*) FROM tasks WHERE severity = '01-Critical' AND cost > 100")
    assert "error" not in out
    assert evidence.queries[0].result.rows == [(0,)]


def test_in_predicates_reject_unknown_values(database):
    out, _ = execute(database, "SELECT COUNT(*) FROM tasks WHERE severity IN ('01-Critical', 'Impossible')")
    assert json.loads(out)["unknown_values"] == ["Impossible"]


def test_incomplete_domain_never_proves_absence(database):
    adapter, _ = database
    adapter.execute("INSERT INTO tasks SELECT CAST(range AS VARCHAR), 1 FROM range(50)")
    out, evidence = execute(database, "SELECT COUNT(*) FROM tasks WHERE severity = 'Absent'")
    assert "error" not in out
    assert evidence.queries[0].result.rows == [(0,)]


def test_numeric_request_blocks_document_search_then_runs_sql(database):
    adapter, model = database

    class Model:
        def __init__(self):
            self.calls = []

        def chat(self, messages, tools):
            self.calls.append((list(messages), tools))
            if len(self.calls) == 1:
                return {"tool_calls": [{"id": "a", "function": {"name": "search_documents", "arguments": '{"query":"cost"}'}}]}
            if len(self.calls) == 2:
                return {"tool_calls": [{"id": "b", "function": {"name": "run_sql", "arguments": '{"sql":"SELECT SUM(cost) FROM tasks","purpose":"Total cost"}'}}]}
            return {"content": "Total cost is 35 [[Q1:R1]]."}

    llm = Model()
    result = AgentOrchestrator(llm, adapter, None, model, config=AgentConfig(answerability_check=False)).run("What is the total cost?")
    assert result.success
    assert len(result.evidence_store.queries) == 1
    assert "StructuredQueryRequired" in llm.calls[1][0][-1]["content"]
    assert [t["function"]["name"] for t in llm.calls[0][1]] == ["run_sql"]
    assert requires_structured_sql("What was the total order value for each year?")
    assert not requires_structured_sql("Explain the customer's complaint text")


def test_wrong_scalar_narration_gets_one_retry_then_exact_receipt(database):
    adapter, model = database

    class Model:
        calls = 0

        def chat(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return {"tool_calls": [{"id": "a", "function": {"name": "run_sql", "arguments": '{"sql":"SELECT SUM(cost) FROM tasks","purpose":"Total cost"}'}}]}
            return {"content": "Total cost is 3500 [[Q1:R1]]."}

    llm = Model()
    result = AgentOrchestrator(llm, adapter, None, model, config=AgentConfig(answerability_check=False)).run("What is the total cost?")
    assert llm.calls == 3
    assert result.citation_report.is_clean
    assert "returned 35 [[Q1:R1]]" in result.answer
    assert "3500" not in result.answer


def test_empty_model_output_is_never_reported_as_success(database):
    adapter, model = database

    class EmptyModel:
        calls = 0

        def chat(self, messages, tools):
            self.calls += 1
            return {"content": "", "finish_reason": "stop"}

    llm = EmptyModel()
    result = AgentOrchestrator(llm, adapter, None, model, config=AgentConfig(answerability_check=False)).run("What is the total cost?")
    assert llm.calls == 2
    assert not result.success and not result.citation_report.is_clean
    assert result.error == "empty_model_response"
    assert result.answer.strip()
