"""Unit tests for deterministic chart planner (WP2).

Verifies all shape classifications:
- Empty or all null results -> table fallback
- Single value / row -> KPI card
- Time series (temporal + numeric) -> line chart
- Categorical + numeric -> horizontal bar (sorted top 20)
- Signed change column -> diverging bar (with positive/negative split)
- Too many categories (>30) -> table fallback
- Provable row-ID equality: every plotted value exactly equals the cell in its cited row ID
"""


from datamind.adapters.base import QueryResult
from datamind.agent.evidence import QueryRecord
from datamind.trust.chart_planner import plan_chart


def _make_query_record(columns: list[str], rows: list[list]) -> QueryRecord:
    qr = QueryResult(
        query_id="LOCAL_Q1",
        elapsed_ms=5.0,
        columns=columns,
        rows=rows,
        truncated=False,
    )
    return QueryRecord(
        query_num=1,
        query_label="Q1",
        sql="SELECT * FROM test;",
        purpose="Testing chart planner",
        result=qr,
        row_ids=[f"Q1:R{i+1}" for i in range(len(rows))],
    )


def test_chart_empty_or_all_nulls():
    """Empty results or all null columns fallback to table."""
    rec_empty = _make_query_record(["product_name", "revenue"], [])
    spec_empty = plan_chart(rec_empty)
    assert spec_empty.type == "table"

    rec_nulls = _make_query_record(["product_name", "revenue"], [[None, None], [None, None]])
    spec_nulls = plan_chart(rec_nulls)
    assert spec_nulls.type == "table"


def test_chart_single_value_kpi():
    """Single scalar or single row with metric produces KPI card."""
    # 1. Scalar
    rec_scalar = _make_query_record(["total_revenue"], [[1589420.50]])
    spec_scalar = plan_chart(rec_scalar)
    assert spec_scalar.type == "kpi"
    assert "$1,589,420.50" in spec_scalar.kpi_value
    assert spec_scalar.points[0]["row_id"] == "Q1:R1"

    # 2. Key-value single row
    rec_kv = _make_query_record(["metric_name", "amount"], [["Global Sales", 950000]])
    spec_kv = plan_chart(rec_kv)
    assert spec_kv.type == "kpi"
    assert spec_kv.kpi_label == "Global Sales"


def test_chart_time_series_line():
    """Temporal column + numeric columns produces line chart."""
    rows = [
        ["2026-01-01", 120000.0, 45000.0],
        ["2026-02-01", 145000.0, 52000.0],
        ["2026-03-01", 110000.0, 39000.0],
    ]
    rec = _make_query_record(["order_month", "revenue", "cogs"], rows)
    spec = plan_chart(rec)

    assert spec.type == "line"
    assert spec.x.column == "order_month"
    assert len(spec.y) == 2
    assert spec.y[0].column == "revenue"
    assert spec.y[1].column == "cogs"
    assert len(spec.points) == 3
    assert spec.points[0]["row_id"] == "Q1:R1"
    assert spec.points[0]["x"] == "2026-01-01"


def test_chart_signed_change_diverging():
    """Signed change column produces diverging bar chart."""
    rows = [
        ["Novaship", -53803.23],
        ["SecureVault", 3482.85],
        ["OmniChat", 12450.00],
        ["CloudSync", -8120.40],
    ]
    rec = _make_query_record(["product_name", "mom_change"], rows)
    spec = plan_chart(rec)

    assert spec.type == "diverging_bar"
    assert spec.x.column == "product_name"
    assert spec.y[0].column == "mom_change"
    assert len(spec.points) == 4
    assert spec.points[0]["row_id"] == "Q1:R1"
    assert spec.points[0]["y"] == -53803.23
    assert spec.points[1]["y"] == 3482.85


def test_chart_categorical_horizontal_bar():
    """Categorical column with <= 30 items + numeric column produces horizontal bar."""
    rows = [
        ["Product A", 50000],
        ["Product B", 85000],
        ["Product C", 20000],
    ]
    rec = _make_query_record(["product_name", "total_sales"], rows)
    spec = plan_chart(rec)

    assert spec.type == "horizontal_bar"
    assert spec.x.column == "product_name"
    assert spec.y[0].column == "total_sales"
    # Verify sorted descending by value
    assert spec.points[0]["x"] == "Product B"
    assert spec.points[0]["y"] == 85000.0
    assert spec.points[1]["x"] == "Product A"
    assert spec.points[2]["x"] == "Product C"


def test_chart_too_many_categories_fallback():
    """Categorical column with > 30 distinct values falls back to table."""
    rows = [[f"Customer_{i}", 100 * i] for i in range(35)]
    rec = _make_query_record(["customer_id", "total_spend"], rows)
    spec = plan_chart(rec)
    assert spec.type == "table"


def test_every_plotted_value_equals_row_cell():
    """Invariant: every plotted value in spec.points strictly equals the database cell in its row_id."""
    rows = [
        ["Alpha", 12050.50],
        ["Beta", 94200.75],
        ["Gamma", 33100.25],
    ]
    rec = _make_query_record(["product_name", "revenue"], rows)
    spec = plan_chart(rec)

    assert spec.type == "horizontal_bar"
    for pt in spec.points:
        row_id = pt["row_id"]
        # Parse row number from Q1:R<n>
        row_num = int(row_id.split(":")[1].replace("R", ""))
        original_row = rows[row_num - 1]

        # In horizontal bar, x is category, y is numeric value
        assert pt["x"] == original_row[0]
        assert pt["y"] == float(original_row[1])
