"""Unit tests for SecondOpinionEngine cross-model query consensus and assumptions diffing."""

import pytest

from datamind.adapters.duckdb_adapter import DuckDBAdapter
from datamind.agent.second_opinion import SecondOpinionEngine
from datamind.guardrails.sql_guard import SQLGuard


@pytest.fixture
def test_engine():
    adapter = DuckDBAdapter("examples/primary/demo.duckdb", read_only=True)
    guard = SQLGuard(approved_tables={"sales", "products"})
    engine = SecondOpinionEngine(adapter, guard)
    yield engine
    adapter.close()


def test_second_opinion_exact_consensus(test_engine):
    sql1 = "SELECT product_name, SUM(amount) AS total FROM sales GROUP BY product_name ORDER BY total DESC"
    sql2 = "SELECT product_name, SUM(amount) AS total FROM sales GROUP BY product_name ORDER BY total DESC"

    res = test_engine.evaluate_queries(sql1, sql2, primary_model="gemma4:e2b", secondary_model="verifier_model")
    assert res.verdict == "AGREE_EXACT"
    assert "identical result sets" in res.explanation
    assert len(res.assumptions_diff.tables_diff) == 0


def test_second_opinion_disagreement_with_diff(test_engine):
    # Query 1 has no filter, Query 2 has filter on amount > 50000
    sql1 = "SELECT product_name, amount FROM sales"
    sql2 = "SELECT product_name, amount FROM sales WHERE amount > 50000"

    res = test_engine.evaluate_queries(sql1, sql2, primary_model="gemma4:e2b", secondary_model="gemma4:e4b")
    assert res.verdict == "DISAGREE"
    assert res.primary_row_count != res.secondary_row_count
    assert len(res.assumptions_diff.filters_diff) > 0


def test_second_opinion_security_blocked(test_engine):
    sql_safe = "SELECT COUNT(*) FROM sales"
    sql_unsafe = "DROP TABLE sales"

    res = test_engine.evaluate_queries(sql_safe, sql_unsafe)
    assert res.verdict == "ERROR"
    assert "SQL Security Rejected" in res.verdict_label
