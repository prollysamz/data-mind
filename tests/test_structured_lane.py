"""Tests for the structured query lane and the sibling fan-out lint check.

The lane must stay schema-driven: it may only answer from metrics the active semantic
model declares, and it must refuse anything that narrows or breaks down the result.
"""

import pytest

from datamind.agent.techniques.structured_query_lane import (
    compile_structured_spec,
    try_structured_lane,
)
from datamind.guardrails.query_lint import QueryLinter
from datamind.semantic.model import (
    ColumnDef,
    JoinDef,
    MetricDef,
    SemanticModel,
    TableDef,
)


def build_model() -> SemanticModel:
    """A small invented schema, unrelated to any shipped dataset."""
    return SemanticModel(
        name="widgets",
        description="Widget shipments",
        tables=[
            TableDef(
                name="shipments",
                description="One row per shipment",
                columns=[
                    ColumnDef(name="shipment_id", type="VARCHAR", is_primary_key=True),
                    ColumnDef(name="region", type="VARCHAR"),
                ],
            ),
            TableDef(
                name="shipment_lines",
                description="One row per line",
                columns=[
                    ColumnDef(name="shipment_id", type="VARCHAR"),
                    ColumnDef(name="amount", type="DECIMAL"),
                ],
            ),
            TableDef(
                name="shipment_fees",
                description="One row per fee",
                columns=[
                    ColumnDef(name="shipment_id", type="VARCHAR"),
                    ColumnDef(name="fee", type="DECIMAL"),
                ],
            ),
        ],
        joins=[
            JoinDef(from_table="shipments", to_table="shipment_lines", on_condition="shipments.shipment_id = shipment_lines.shipment_id"),
            JoinDef(from_table="shipments", to_table="shipment_fees", on_condition="shipments.shipment_id = shipment_fees.shipment_id"),
        ],
        metrics=[
            MetricDef(
                name="shipment_value",
                table="shipment_lines",
                expression="SUM(amount)",
                dimensions=["region"],
            ),
            MetricDef(
                name="fee_total",
                table="shipment_fees",
                expression="SUM(fee)",
                sql_template="SELECT SUM(fee) AS fee_total FROM shipment_fees",
            ),
        ],
    )


@pytest.fixture
def model() -> SemanticModel:
    return build_model()


def test_matches_a_declared_metric(model):
    sql = try_structured_lane("What is the shipment value?", model)
    assert sql == "SELECT SUM(amount) AS shipment_value FROM shipment_lines;"


def test_uses_the_metrics_own_sql_template(model):
    assert try_structured_lane("What is the fee total?", model) == (
        "SELECT SUM(fee) AS fee_total FROM shipment_fees;"
    )


@pytest.mark.parametrize("question", [
    "What is the shipment value by region?",      # breakdown
    "What is the shipment value per region?",     # breakdown
    "Which region has the highest shipment value?",  # ranking
    "What is the shipment value in 2017?",        # a period
    "What is the shipment value for SP?",         # a code
    "What is the shipment value for Acme?",       # a named entity
    "What is the shipment value excluding returns?",  # a subset
    "What was the shipment value trend?",         # over time
])
def test_refuses_anything_the_bare_metric_cannot_answer(model, question):
    assert try_structured_lane(question, model) is None


def test_refuses_questions_naming_no_metric(model):
    assert try_structured_lane("How many customers complained?", model) is None


def test_refuses_when_two_metrics_match(model):
    """Two metrics whose names both fit the wording: the question is not specific enough."""
    model.metrics.append(MetricDef(name="value_shipment", table="shipment_lines", expression="AVG(amount)"))
    assert try_structured_lane("What is the shipment value?", model) is None


def test_lane_is_schema_driven_not_dataset_specific(model):
    """Renaming the metric changes what the lane answers; nothing is hard-coded."""
    assert try_structured_lane("What is the parcel worth?", model) is None
    model.metrics[0].name = "parcel_worth"
    assert try_structured_lane("What is the parcel worth?", model) == (
        "SELECT SUM(amount) AS parcel_worth FROM shipment_lines;"
    )


def test_empty_model_and_blank_question_are_safe():
    empty = SemanticModel(name="e", description="", tables=[], joins=[], metrics=[])
    assert try_structured_lane("What is the revenue?", empty) is None
    assert try_structured_lane("   ", build_model()) is None


def test_compile_rejects_undeclared_dimensions(model):
    spec_ok = {"metric": "shipment_value", "dimensions": ["region"]}
    assert "GROUP BY region" in compile_structured_spec(spec_ok, model)
    spec_bad = {"metric": "shipment_value", "dimensions": ["secret_column"]}
    assert compile_structured_spec(spec_bad, model) is None


def test_compile_rejects_unknown_metric_and_bad_limit(model):
    assert compile_structured_spec({"metric": "nope"}, model) is None
    assert compile_structured_spec({"metric": "shipment_value", "limit": "ten"}, model) is None


def test_sibling_fan_out_is_flagged(model):
    """Joining one parent to two child tables multiplies their rows together."""
    linter = QueryLinter(model)
    findings, _ = linter.lint_query(
        "SELECT SUM(l.amount), SUM(f.fee) FROM shipments s "
        "JOIN shipment_lines l ON s.shipment_id = l.shipment_id "
        "JOIN shipment_fees f ON s.shipment_id = f.shipment_id",
        question="total shipment value and fees",
    )
    assert "sibling_fan_out" in {f.check_name for f in findings}


def test_single_child_join_is_not_flagged(model):
    linter = QueryLinter(model)
    findings, _ = linter.lint_query(
        "SELECT SUM(l.amount) FROM shipments s "
        "JOIN shipment_lines l ON s.shipment_id = l.shipment_id",
        question="total shipment value",
    )
    assert "sibling_fan_out" not in {f.check_name for f in findings}
