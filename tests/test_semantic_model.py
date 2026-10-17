"""Unit tests for semantic model parser, loader, and prompt context generator."""

from pathlib import Path
import pytest

from datamind.semantic.loader import load_semantic_model
from datamind.semantic.model import SemanticModel


def test_load_semantic_model():
    model_path = Path("examples/primary/semantic_model.yaml")
    assert model_path.exists(), "semantic_model.yaml should exist"

    model = load_semantic_model(model_path)
    assert isinstance(model, SemanticModel)
    assert model.name == "saas_sales_and_support"

    # Tables verification
    table_names = model.get_approved_table_names()
    assert "sales" in table_names
    assert "products" in table_names
    assert "support_tickets" in table_names

    sales_table = model.get_table("SALES")
    assert sales_table is not None
    assert "amount" in sales_table.column_names()
    assert "order_month" in sales_table.column_names()

    # Metrics verification
    mom_metric = model.get_metric("mom_revenue_decline")
    assert mom_metric is not None
    assert "LAG" in mom_metric.expression

    # Joins verification
    assert len(model.joins) >= 1
    assert model.joins[0].from_table == "SALES"

    # Verified queries
    assert len(model.verified_queries) >= 1
    assert "WITH monthly_revenue" in model.verified_queries[0].sql

    # Prompt context rendering
    prompt_str = model.to_prompt_context()
    assert "# Semantic Data Model" in prompt_str
    assert "SALES" in prompt_str
    assert "mom_revenue_decline" in prompt_str


def test_load_nonexistent_file_raises():
    with pytest.raises(FileNotFoundError):
        load_semantic_model("nonexistent_model.yaml")


def test_load_olist_semantic_model():
    model_path = Path("examples/olist/semantic_model.yaml")
    assert model_path.exists(), "olist semantic_model.yaml should exist"

    model = load_semantic_model(model_path)
    assert isinstance(model, SemanticModel)
    assert model.name == "olist_ecommerce"
    assert model.default_currency == "BRL"
    assert model.currency_symbol == "R$"

    table_names = model.get_approved_table_names()
    assert "olist_orders" in table_names
    assert "olist_order_items" in table_names
    assert "olist_order_reviews" in table_names
    assert len(model.tables) == 8

    # Metrics
    rev_metric = model.get_metric("net_sales_revenue")
    assert rev_metric is not None
    assert rev_metric.unit == "BRL"

    # Joins
    assert len(model.joins) == 7

