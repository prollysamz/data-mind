"""Database-backed regression tests for schema context and date diagnostics."""

import datetime

import pytest

from datamind.adapters.duckdb_adapter import DuckDBAdapter
from datamind.agent.answerability import screen_question
from datamind.agent.evidence import EvidenceStore
from datamind.agent.schema_context import collect_schema_examples
from datamind.agent.tools import execute_sql_tool
from datamind.guardrails.sql_guard import SQLGuard
from datamind.semantic.model import ColumnDef, SemanticModel, TableDef


@pytest.fixture
def setup():
    adapter = DuckDBAdapter()
    adapter.execute("CREATE TABLE events (id INTEGER, occurred DATE, status VARCHAR, email VARCHAR, value INTEGER)")
    adapter.execute("INSERT INTO events VALUES (1, DATE '2020-01-01', '01-Open', 'a@example.invalid', 5), (2, DATE '2021-02-01', '02-Closed', 'b@example.invalid', 7), (3, NULL, '01-Open', NULL, NULL)")
    model = SemanticModel(tables=[TableDef(name="events", primary_key=["id"], columns=[
        ColumnDef(name="id", type="INTEGER"), ColumnDef(name="occurred", type="DATE", description="Date of event"),
        ColumnDef(name="status", type="VARCHAR", description="Event workflow status"),
        ColumnDef(name="email", type="VARCHAR"), ColumnDef(name="value", type="INTEGER"),
    ])])
    yield adapter, model, SQLGuard({"events"}), EvidenceStore()
    adapter.close()


def run(setup, sql):
    adapter, model, guard, evidence = setup
    return execute_sql_tool(sql, "Original request", guard, adapter, evidence, model)


def test_renderer_and_live_examples_include_schema_information_without_contacts(setup):
    adapter, model, guard, evidence = setup
    samples = collect_schema_examples(model, "Show events by status and email", adapter, guard, evidence)
    prompt = model.to_prompt_context(samples)
    assert "Primary key: id" in prompt and "PK" in prompt
    assert "Date of event" in prompt
    assert "01-Open" in prompt and "not an exhaustive domain" in prompt
    assert "events.email" not in samples
    assert len(evidence.validation_queries) == 1


def test_prefixed_compact_categorical_names_are_sampled(setup):
    adapter, _, guard, evidence = setup
    adapter.execute("ALTER TABLE events RENAME status TO e_orderpriority")
    model = SemanticModel(tables=[TableDef(name="events", columns=[ColumnDef(name="e_orderpriority", type="VARCHAR", description="Order priority code")])])
    examples = collect_schema_examples(model, "Orders by priority", adapter, guard, evidence)
    assert examples["events.e_orderpriority"] == ["01-Open", "02-Closed"]


def test_camel_case_filter_value_is_not_a_missing_schema_attribute(setup):
    assessment = screen_question("Count events for CloudSync", setup[1])
    assert assessment.verdict == "answerable"
    assert not assessment.ungrounded_terms


@pytest.mark.parametrize("identifier", ["status", '"status"'])
def test_filter_validation_preserves_identifier_quoting(setup, identifier):
    run(setup, f"SELECT COUNT(*) FROM events WHERE {identifier} = '01-Open'")
    assert f"SELECT DISTINCT {identifier} FROM" in setup[3].validation_queries[0]["sql"]
    assert setup[3].queries[0].result.rows == [(2,)]


def test_empty_date_filter_has_separate_whole_table_receipt(setup):
    output = run(setup, "SELECT * FROM events e WHERE e.occurred >= DATE '2030-01-01'")
    evidence = setup[3]
    assert evidence.queries[0].result.rows == []
    assert evidence.queries[1].kind == "diagnostic"
    assert evidence.queries[1].result.rows == [(datetime.date(2020, 1, 1), datetime.date(2021, 2, 1), 3, 2)]
    assert "[[Q2:R1]]" in output and "No rows returned" in output
    assert "original filters excluded" in evidence.queries[1].purpose
    assert evidence.diagnostics[0]["source_query"] == "Q1"


def test_null_aggregate_is_diagnosed_but_zero_is_not(setup):
    run(setup, "SELECT SUM(value) FROM events WHERE occurred >= DATE '2030-01-01'")
    assert setup[3].diagnostics[0]["trigger"] == "null_aggregate"
    setup[3].clear()
    run(setup, "SELECT COUNT(*) FROM events WHERE occurred >= DATE '2030-01-01'")
    assert setup[3].queries[0].result.rows == [(0,)]
    assert not setup[3].diagnostics


def test_source_with_no_dates_does_not_invent_a_range(setup):
    setup[0].execute("UPDATE events SET occurred = NULL")
    run(setup, "SELECT * FROM events WHERE occurred > DATE '2020-01-01'")
    diagnostic = setup[3].diagnostics[0]
    assert diagnostic["earliest_date"] is None and diagnostic["latest_date"] is None
    assert diagnostic["source_rows"] == 3 and diagnostic["dated_rows"] == 0


def test_join_and_non_date_emptiness_are_not_overdiagnosed(setup):
    run(setup, "SELECT * FROM events WHERE id = 999")
    assert not setup[3].diagnostics
    setup[3].clear()
    run(setup, "SELECT e.id FROM events e JOIN events x ON e.id=x.id WHERE e.occurred > DATE '2030-01-01'")
    assert not setup[3].diagnostics


def test_single_null_cell_without_aggregation_is_not_called_an_empty_aggregate(setup):
    run(setup, "SELECT NULL FROM events WHERE occurred = DATE '2020-01-01'")
    assert not setup[3].diagnostics


def test_diagnostic_failure_preserves_original_empty_result(setup, monkeypatch):
    execute = setup[0].execute

    def fail_diagnostic(sql):
        if "earliest_date" in sql:
            raise RuntimeError("unavailable")
        return execute(sql)

    monkeypatch.setattr(setup[0], "execute", fail_diagnostic)
    output = run(setup, "SELECT * FROM events WHERE occurred > DATE '2030-01-01'")
    assert "No rows returned" in output
    assert setup[3].diagnostics[0]["status"] == "unavailable"
