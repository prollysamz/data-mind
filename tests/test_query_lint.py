"""Unit tests for deterministic query linting and assumptions card generation."""

import pytest
from datamind.guardrails.query_lint import QueryLinter, AssumptionsCard, QueryLintFinding


def test_join_fan_out_detection():
    linter = QueryLinter()

    # Negative case: Aggregating order_id without DISTINCT across 1-to-many join
    bad_sql = """
        SELECT o.order_id, COUNT(o.order_id) AS total_orders
        FROM olist_orders o
        JOIN olist_order_items i ON o.order_id = i.order_id
        WHERE o.order_status = 'delivered'
        GROUP BY o.order_id;
    """
    findings, card = linter.lint_query(bad_sql, question="Total delivered orders")
    check_names = [f.check_name for f in findings]
    assert "join_fan_out" in check_names
    assert card.badge_status == "PARTIALLY_VERIFIED"
    assert "Join fan-out detected" in card.badge_reason

    # Positive case: Aggregating order_id WITH DISTINCT across 1-to-many join
    good_sql = """
        SELECT COUNT(DISTINCT o.order_id) AS total_orders
        FROM olist_orders o
        JOIN olist_order_items i ON o.order_id = i.order_id
        WHERE o.order_status = 'delivered';
    """
    findings, card = linter.lint_query(good_sql, question="Total delivered orders")
    check_names = [f.check_name for f in findings]
    assert "join_fan_out" not in check_names


def test_default_filter_echo():
    linter = QueryLinter()

    # Negative case: Querying orders without order_status = 'delivered' on general query
    bad_sql = "SELECT order_id, order_purchase_timestamp FROM olist_orders;"
    findings, card = linter.lint_query(bad_sql, question="What was our order volume?")
    check_names = [f.check_name for f in findings]
    assert "missing_default_filter" in check_names
    assert card.badge_status == "PARTIALLY_VERIFIED"

    # Positive case: Querying orders WITH order_status = 'delivered'
    good_sql = "SELECT order_id FROM olist_orders WHERE order_status = 'delivered';"
    findings, card = linter.lint_query(good_sql, question="What was our order volume?")
    check_names = [f.check_name for f in findings]
    assert "missing_default_filter" not in check_names
    assert card.badge_status == "VERIFIED"

    # Positive exempt case: Query explicitly asks about canceled orders
    canceled_sql = "SELECT COUNT(*) FROM olist_orders WHERE order_status = 'canceled';"
    findings, card = linter.lint_query(canceled_sql, question="How many orders were canceled?")
    check_names = [f.check_name for f in findings]
    assert "missing_default_filter" not in check_names


def test_empty_result_check():
    linter = QueryLinter()
    sql = "SELECT order_id FROM olist_orders WHERE order_status = 'delivered';"
    findings, card = linter.lint_query(sql, question="Delivered orders", result_rows=[])
    check_names = [f.check_name for f in findings]
    assert "empty_result" in check_names
    assert card.badge_status == "PARTIALLY_VERIFIED"


def test_null_heavy_result_check():
    linter = QueryLinter()
    sql = "SELECT price, freight_value FROM olist_order_items;"
    # 3 out of 4 cells are None (>50% null)
    rows = [(None, None), (None, 15.0)]
    findings, card = linter.lint_query(sql, question="Price and freight", result_rows=rows)
    check_names = [f.check_name for f in findings]
    assert "null_heavy_result" in check_names
    assert card.badge_status == "PARTIALLY_VERIFIED"


def test_row_limit_truncation():
    linter = QueryLinter()
    sql = "SELECT * FROM olist_orders LIMIT 50;"
    # 50 rows returned matching LIMIT 50
    rows = [(f"id_{i}",) for i in range(50)]
    findings, card = linter.lint_query(sql, question="Show orders", result_rows=rows)
    check_names = [f.check_name for f in findings]
    assert "row_limit_truncation" in check_names
    assert card.is_truncated is True
    assert card.badge_status == "PARTIALLY_VERIFIED"


def test_assumptions_card_markdown():
    linter = QueryLinter()
    sql = """
        SELECT
            p.product_category_name,
            ROUND(SUM(i.price), 2) AS total_revenue
        FROM olist_order_items i
        JOIN olist_orders o ON i.order_id = o.order_id
        JOIN olist_products p ON i.product_id = p.product_id
        WHERE o.order_status = 'delivered'
          AND EXTRACT(YEAR FROM o.order_purchase_timestamp) = 2017
        GROUP BY p.product_category_name
        LIMIT 10;
    """
    rows = [(f"cat_{i}", 100.0) for i in range(5)]
    findings, card = linter.lint_query(sql, question="2017 revenue by category", result_rows=rows)
    assert len(findings) == 0
    assert card.badge_status == "VERIFIED"
    assert "olist_order_items" in card.tables
    assert "olist_orders" in card.tables
    assert len(card.join_keys) >= 2
    assert "SUM" in card.metric_expressions[0]

    md = card.to_markdown()
    assert "Assumptions & Query Verification Card" in md
    assert "VERIFIED" in md
    assert "olist_order_items" in md


def test_unrequested_grouping_flags_extra_dimension():
    from datamind.guardrails.query_lint import QueryLinter

    sql = ("SELECT product_name, order_month, SUM(amount) AS monthly_revenue FROM SALES "
           "GROUP BY product_name, order_month ORDER BY order_month")
    findings, card = QueryLinter().lint_query(sql, question="What was the total sales revenue for each month?")
    flagged = [f for f in findings if f.check_name == "unrequested_grouping"]
    assert [f.message.split("'")[1] for f in flagged] == ["product_name"]
    assert card.badge_status == "PARTIALLY_VERIFIED"


def test_requested_grouping_is_not_flagged():
    from datamind.guardrails.query_lint import QueryLinter

    cases = [
        ("SELECT order_month, SUM(amount) FROM SALES GROUP BY order_month",
         "What is the total revenue per month across all products?"),
        ("SELECT order_month, SUM(amount) FROM SALES GROUP BY order_month", "Show monthly sales totals."),
        ("SELECT p.category, SUM(s.amount) FROM SALES s JOIN PRODUCTS p ON s.product_id = p.product_id GROUP BY p.category",
         "What is revenue by product categories?"),
        ("WITH m AS (SELECT product_name, order_month, SUM(amount) AS v FROM SALES GROUP BY product_name, order_month) "
         "SELECT product_name, v - LAG(v) OVER (PARTITION BY product_name ORDER BY order_month) FROM m",
         "Which products experienced the largest month-over-month revenue decline?"),
    ]
    for sql, question in cases:
        findings, _ = QueryLinter().lint_query(sql, question=question)
        assert not [f for f in findings if f.check_name == "unrequested_grouping"], (sql, question)
