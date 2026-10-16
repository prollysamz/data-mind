"""Unit tests for SQLGuard security and validation pipeline."""

import pytest

from datamind.guardrails.sql_guard import SQLGuard, SQLSecurityError

APPROVED_TABLES = {"sales", "products", "support_tickets"}


@pytest.fixture
def guard():
    return SQLGuard(approved_tables=APPROVED_TABLES, dialect="duckdb")


def test_valid_select(guard):
    sql = "SELECT product_name, SUM(amount) FROM SALES GROUP BY product_name"
    sanitized = guard.validate(sql)
    assert "SALES" in sanitized or "sales" in sanitized


def test_valid_cte_with_multiple_aliases(guard):
    sql = """
    WITH monthly_revenue AS (
        SELECT product_name, order_month, SUM(amount) AS monthly_sales
        FROM SALES
        GROUP BY product_name, order_month
    ),
    revenue_changes AS (
        SELECT
            product_name,
            order_month,
            monthly_sales,
            LAG(monthly_sales) OVER (PARTITION BY product_name ORDER BY order_month) AS prev_month_sales
        FROM monthly_revenue
    )
    SELECT * FROM revenue_changes WHERE prev_month_sales IS NOT NULL
    """
    sanitized = guard.validate(sql)
    assert "revenue_changes" in sanitized


def test_valid_join_with_on(guard):
    sql = """
    SELECT s.order_id, p.category, s.amount
    FROM SALES s
    JOIN PRODUCTS p ON s.product_id = p.product_id
    """
    sanitized = guard.validate(sql)
    assert "JOIN" in sanitized


def test_reject_unauthorized_table(guard):
    sql = "SELECT * FROM EMPLOYEES"
    with pytest.raises(SQLSecurityError) as exc_info:
        guard.validate(sql)
    assert exc_info.value.violation_type == "unauthorized_table"
    assert "EMPLOYEES" in exc_info.value.message


def test_reject_insert(guard):
    sql = "INSERT INTO SALES (order_id, line_no, amount) VALUES (1, 1, 100.0)"
    with pytest.raises(SQLSecurityError) as exc_info:
        guard.validate(sql)
    assert exc_info.value.violation_type in ("prohibited_statement", "prohibited_node")


def test_reject_drop(guard):
    sql = "DROP TABLE SALES"
    with pytest.raises(SQLSecurityError) as exc_info:
        guard.validate(sql)
    assert exc_info.value.violation_type in ("prohibited_statement", "prohibited_node")


def test_reject_update(guard):
    sql = "UPDATE SALES SET amount = 0 WHERE order_id = 1"
    with pytest.raises(SQLSecurityError) as exc_info:
        guard.validate(sql)
    assert exc_info.value.violation_type in ("prohibited_statement", "prohibited_node")


def test_reject_delete(guard):
    sql = "DELETE FROM SALES WHERE order_id = 1"
    with pytest.raises(SQLSecurityError) as exc_info:
        guard.validate(sql)
    assert exc_info.value.violation_type in ("prohibited_statement", "prohibited_node")


def test_reject_multiple_statements(guard):
    sql = "SELECT * FROM SALES; DROP TABLE SALES;"
    with pytest.raises(SQLSecurityError) as exc_info:
        guard.validate(sql)
    assert exc_info.value.violation_type == "multiple_statements"


def test_reject_cross_join(guard):
    sql = "SELECT * FROM SALES CROSS JOIN PRODUCTS"
    with pytest.raises(SQLSecurityError) as exc_info:
        guard.validate(sql)
    assert exc_info.value.violation_type == "cross_join"


def test_reject_unconditional_comma_join(guard):
    sql = "SELECT * FROM SALES, PRODUCTS"
    with pytest.raises(SQLSecurityError) as exc_info:
        guard.validate(sql)
    assert exc_info.value.violation_type == "unconditional_join"


def test_reject_dangerous_function(guard):
    sql = "SELECT * FROM read_csv('confidential.csv')"
    with pytest.raises(SQLSecurityError) as exc_info:
        guard.validate(sql)
    assert exc_info.value.violation_type in ("dangerous_function", "unauthorized_table")
