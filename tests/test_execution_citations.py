"""Empty executions have provenance, but no fabricated result rows or measures."""

import pytest

from datamind.adapters.base import QueryResult
from datamind.adapters.duckdb_adapter import DuckDBAdapter
from datamind.agent.empty_results import empty_execution_receipt
from datamind.agent.evidence import EvidenceStore
from datamind.agent.orchestrator import AgentOrchestrator
from datamind.agent.verifier import verify_citations
from datamind.config import AgentConfig
from datamind.semantic.model import ColumnDef, SemanticModel, TableDef
from datamind.trust.receipts import ReceiptGenerator, ReceiptVerifier


def empty_store():
    store = EvidenceStore()
    store.add_query("SELECT amount FROM sales WHERE amount > 100", "Requested records",
                    QueryResult(["amount"], [], "real-execution-id", 1.0, False))
    return store


def test_execution_citation_resolves_without_inventing_a_row():
    store = empty_store()
    report = verify_citations("The executed query returned no matching rows [[Q1:EXEC]].", store)
    assert report.is_clean and report.valid_count == 1
    assert report.citations[0].evidence_type == "query_execution"
    assert report.citations[0].resolved_data["query_id"] == "real-execution-id"
    assert not store.has_id("Q1:R1")
    assert not verify_citations("No matching rows [[Q1:R1]].", store).is_clean
    assert not verify_citations("No matching rows [[Q99:EXEC]].", store).is_clean
    assert not verify_citations("No matching rows [Q1:EXEC].", store).is_clean
    store.clear()
    assert not store.has_id("Q1:EXEC")


@pytest.mark.parametrize("amount", [0, 99, 1500000])
def test_execution_metadata_cannot_ground_measures_or_borrow_diagnostic_cells(amount):
    store = empty_store()
    store.add_query("SELECT COUNT(*) FROM sales", "Whole-table diagnostic",
                    QueryResult(["source_rows"], [(amount,)], "coverage-id", 1.0, False), kind="diagnostic")
    report = verify_citations(f"Revenue is ${amount} [[Q1:EXEC]]. Source rows: {amount} [[Q2:R1]].", store)
    assert not report.is_clean
    assert any(check.status == "UNSUPPORTED" and "Execution metadata" in check.message for check in report.numeric_checks)


def test_empty_fallback_skips_truncated_or_multiple_answer_queries():
    store = empty_store()
    assert empty_execution_receipt(store)
    store.queries[0].result.truncated = True
    assert empty_execution_receipt(store) is None
    store.queries[0].result.truncated = False
    store.add_query("SELECT 1", "Another answer", QueryResult(["amount"], [(1,)], "other-id", 1.0, False))
    assert empty_execution_receipt(store) is None


def test_execution_receipt_round_trips_through_hash_verifier():
    store = empty_store()
    answer = empty_execution_receipt(store)
    receipt = ReceiptGenerator.generate_receipt(
        question="Show matching sales", answer=answer, evidence_store=store,
        citation_report=verify_citations(answer, store), backend_name="duckdb", model_name="test-model",
    )
    assert ReceiptVerifier.verify(receipt)["verified"]


def test_failed_empty_narration_gets_verified_execution_fallback():
    class Model:
        calls = 0

        def chat(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return {"tool_calls": [{"id": "a", "function": {"name": "run_sql", "arguments": '{"sql":"SELECT amount FROM sales WHERE amount > 100","purpose":"Requested records"}'}}]}
            return {"content": "Revenue is $0 [[Q1:R1]]."}

    adapter = DuckDBAdapter()
    try:
        adapter.execute("CREATE TABLE sales (amount INTEGER)")
        adapter.execute("INSERT INTO sales VALUES (10)")
        model = SemanticModel(tables=[TableDef(name="sales", columns=[ColumnDef(name="amount", type="INTEGER")])])
        llm = Model()
        result = AgentOrchestrator(llm, adapter, None, model, config=AgentConfig(answerability_check=False)).run("Show sales above 100")
        assert llm.calls == 3
        assert result.citation_report.is_clean and result.citation_report.valid_count == 1
        assert "[[Q1:EXEC]]" in result.answer and "[[Q1:R1]]" not in result.answer
        assert "measured zero" in result.answer and "$0" not in result.answer
        assert result.evidence_store.queries[0].result.rows == []
    finally:
        adapter.close()
