"""Unit tests for WP-F2 accuracy techniques."""

import pytest
from datamind.semantic.loader import load_semantic_model
from datamind.agent.techniques.schema_pruning import prune_semantic_model
from datamind.agent.techniques.dynamic_few_shot import retrieve_dynamic_few_shot
from datamind.agent.techniques.structured_query_lane import compile_structured_spec, try_structured_lane


@pytest.fixture
def olist_model():
    return load_semantic_model("examples/olist/semantic_model.yaml")


def test_schema_pruning_filters_to_relevant_tables(olist_model):
    q = "What is the overall average customer satisfaction review score?"
    pruned = prune_semantic_model(olist_model, q, max_tables=2)
    table_names = [t.name for t in pruned.tables]
    assert "olist_order_reviews" in table_names
    # Products or sellers should not be included
    assert "olist_sellers" not in table_names


def test_dynamic_few_shot_retrieval(olist_model):
    q = "How many orders were canceled by customers?"
    top_few = retrieve_dynamic_few_shot(olist_model.verified_queries, q, k=1)
    assert len(top_few) == 1
    assert "canceled" in top_few[0].question.lower()


def test_structured_query_lane_total_orders(olist_model):
    q = "What is the total number of delivered orders in the database?"
    sql = try_structured_lane(q, olist_model)
    assert sql is not None
    assert "total_orders" in sql
    assert "delivered" in sql


def test_structured_query_lane_net_revenue(olist_model):
    q = "What is the total net merchandise sales revenue for delivered orders?"
    sql = try_structured_lane(q, olist_model)
    assert sql is not None
    assert "net_sales_revenue" in sql
    assert "SUM" in sql


def test_structured_query_lane_fallthrough(olist_model):
    # Complex query that cannot be cleanly compiled in structured lane falls through to free-form
    q = "Which top 3 customer states placed the most delivered orders?"
    sql = try_structured_lane(q, olist_model)
    assert sql is None
