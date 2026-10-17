"""Deterministic chart planner for DataMind.

Analyzes executed query result sets and semantic model definitions to deterministically
plan charts:
- 1 temporal + 1-4 numeric columns -> line chart
- 1 categorical (<=30 distinct) + 1 numeric -> horizontal bar (top 20 sorted)
- signed change column -> diverging bar (one color for positive, one for negative, zero line)
- single row or single value -> KPI card
- anything else -> table fallback

Chart data points strictly carry row IDs (e.g. Q1:R3) and values extracted directly
from stored query rows. Never uses model-generated numbers.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
import re
from typing import Any, Literal
from pydantic import BaseModel, Field

from datamind.agent.evidence import QueryRecord
from datamind.semantic.model import SemanticModel


class AxisSpec(BaseModel):
    column: str
    label: str
    format: str | None = None  # currency, percent, integer, decimal


class ChartPoint(BaseModel):
    row_id: str
    x: Any
    y: list[Any] | Any


class ChartSpec(BaseModel):
    type: Literal["line", "horizontal_bar", "bar", "diverging_bar", "kpi", "table"]
    title: str
    x: AxisSpec | None = None
    y: list[AxisSpec] = Field(default_factory=list)
    source_query: str = "Q1"
    points: list[dict[str, Any]] = Field(default_factory=list)
    truncated: bool = False
    alt_text: str = ""
    # KPI Card metadata
    kpi_value: Any = None
    kpi_label: str | None = None
    kpi_unit: str | None = None
    note: str | None = None


def _is_numeric(val: Any) -> bool:
    if val is None:
        return False
    if isinstance(val, (int, float, Decimal)):
        return True
    s = str(val).strip().replace("$", "").replace(",", "").rstrip("%")
    try:
        float(s)
        return True
    except ValueError:
        return False


def _to_float(val: Any) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float, Decimal)):
        return float(val)
    s = str(val).strip().replace("$", "").replace(",", "").rstrip("%")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _is_date_str(val: Any) -> bool:
    if isinstance(val, (datetime.date, datetime.datetime)):
        return True
    s = str(val).strip()
    # YYYY-MM, YYYY-MM-DD, or ISO
    return bool(re.match(r"^\d{4}-\d{2}(-\d{2})?", s))


def _classify_column(col_name: str, values: list[Any]) -> str:
    """Classify column as 'temporal', 'signed_change', 'numeric', or 'categorical'."""
    name_lower = col_name.lower()
    non_nulls = [v for v in values if v is not None]

    if not non_nulls:
        return "empty"

    # Temporal detection
    if any(k in name_lower for k in ("month", "date", "year", "day", "timestamp", "period", "time")):
        if any(_is_date_str(v) for v in non_nulls[:10]):
            return "temporal"
    if all(_is_date_str(v) for v in non_nulls[:10]):
        return "temporal"

    # Check numeric
    numeric_count = sum(1 for v in non_nulls if _is_numeric(v))
    if numeric_count / len(non_nulls) >= 0.8:
        # Check signed change
        float_vals = [_to_float(v) for v in non_nulls]
        has_pos = any(v > 0.001 for v in float_vals)
        has_neg = any(v < -0.001 for v in float_vals)
        change_keywords = ("change", "diff", "delta", "mom", "yoy", "growth", "decline", "increase")
        if (has_pos and has_neg) or any(k in name_lower for k in change_keywords):
            return "signed_change"
        return "numeric"

    return "categorical"


def _format_cell(val: Any, fmt: str | None, symbol: str = "$") -> str:
    if val is None:
        return "N/A"
    if fmt == "currency":
        num = _to_float(val)
        return f"{symbol}{num:,.2f}"
    if fmt == "percent":
        num = _to_float(val)
        return f"{num:.1f}%"
    if isinstance(val, (int, float, Decimal)):
        num = float(val)
        return f"{num:,.2f}" if num % 1 != 0 else f"{int(num):,}"
    return str(val)


def plan_chart(
    query_record: QueryRecord,
    semantic_model: SemanticModel | None = None,
    suggested_spec: dict[str, Any] | None = None,
) -> ChartSpec:
    """Deterministically plan the best visual representation from query results."""
    columns = query_record.result.columns
    rows = query_record.result.rows
    q_label = query_record.query_label
    curr_sym = semantic_model.currency_symbol if semantic_model else "$"

    # 1. Empty or all nulls -> table fallback
    if not rows or not columns:
        return ChartSpec(type="table", title="Result Data Table", source_query=q_label)

    # 2. Check for single row or single value -> KPI Card
    if len(rows) == 1:
        row = rows[0]
        # Single cell or 2 columns with label + value
        if len(columns) == 1:
            val = row[0]
            col_name = columns[0]
            fmt = "currency" if any(k in col_name.lower() for k in ("sales", "revenue", "amount", "price", "cost")) else None
            return ChartSpec(
                type="kpi",
                title=col_name.replace("_", " ").title(),
                source_query=q_label,
                kpi_value=_format_cell(val, fmt, curr_sym),
                kpi_label=col_name.replace("_", " ").title(),
                alt_text=f"KPI Metric: {col_name} is {_format_cell(val, fmt, curr_sym)}",
                points=[{"row_id": f"{q_label}:R1", "x": col_name, "y": val}],
            )
        elif len(columns) == 2 and _is_numeric(row[1]) and not _is_numeric(row[0]):
            label = str(row[0])
            val = row[1]
            col_name = columns[1]
            fmt = "currency" if any(k in col_name.lower() for k in ("sales", "revenue", "amount", "price", "cost")) else None
            return ChartSpec(
                type="kpi",
                title=f"{label} {col_name.replace('_', ' ').title()}",
                source_query=q_label,
                kpi_value=_format_cell(val, fmt, curr_sym),
                kpi_label=label,
                alt_text=f"KPI Metric for {label}: {_format_cell(val, fmt, curr_sym)}",
                points=[{"row_id": f"{q_label}:R1", "x": label, "y": val}],
            )

    # Inspect columns
    col_types: dict[str, str] = {}
    col_values: dict[str, list[Any]] = {}
    for idx, c in enumerate(columns):
        vals = [r[idx] for r in rows]
        col_values[c] = vals
        col_types[c] = _classify_column(c, vals)

    temporal_cols = [c for c, t in col_types.items() if t == "temporal"]
    numeric_cols = [c for c, t in col_types.items() if t == "numeric"]
    signed_cols = [c for c, t in col_types.items() if t == "signed_change"]
    categorical_cols = [c for c, t in col_types.items() if t == "categorical"]

    # 3. Signed Change Column -> Diverging Bar Chart
    if signed_cols and (categorical_cols or temporal_cols):
        s_col = signed_cols[0]
        c_col = categorical_cols[0] if categorical_cols else temporal_cols[0]
        c_idx = columns.index(c_col)
        s_idx = columns.index(s_col)

        # Build points
        points = []
        for r_idx, r in enumerate(rows, start=1):
            points.append({
                "row_id": f"{q_label}:R{r_idx}",
                "x": str(r[c_idx]),
                "y": _to_float(r[s_idx]),
            })

        # Deterministic alt text
        pos_cnt = sum(1 for p in points if p["y"] > 0)
        neg_cnt = sum(1 for p in points if p["y"] < 0)
        alt_text = f"Diverging bar chart of {s_col.replace('_', ' ')} across {len(points)} items ({pos_cnt} positive, {neg_cnt} negative)."

        fmt = "currency" if any(k in s_col.lower() for k in ("sales", "revenue", "amount", "price")) else None
        return ChartSpec(
            type="diverging_bar",
            title=f"{s_col.replace('_', ' ').title()} by {c_col.replace('_', ' ').title()}",
            x=AxisSpec(column=c_col, label=c_col.replace("_", " ").title()),
            y=[AxisSpec(column=s_col, label=s_col.replace("_", " ").title(), format=fmt)],
            source_query=q_label,
            points=points,
            alt_text=alt_text,
        )

    # 4. Temporal + 1-4 Numeric Columns -> Line Chart
    if temporal_cols and numeric_cols:
        t_col = temporal_cols[0]
        t_idx = columns.index(t_col)
        selected_num_cols = numeric_cols[:4]

        points = []
        for r_idx, r in enumerate(rows, start=1):
            y_vals = [_to_float(r[columns.index(nc)]) for nc in selected_num_cols]
            points.append({
                "row_id": f"{q_label}:R{r_idx}",
                "x": str(r[t_idx]),
                "y": y_vals if len(selected_num_cols) > 1 else y_vals[0],
            })

        y_specs = []
        for nc in selected_num_cols:
            fmt = "currency" if any(k in nc.lower() for k in ("sales", "revenue", "amount", "price")) else None
            y_specs.append(AxisSpec(column=nc, label=nc.replace("_", " ").title(), format=fmt))

        time_range = f"from {points[0]['x']} to {points[-1]['x']}" if len(points) >= 2 else f"at {points[0]['x']}"
        alt_text = f"Line chart of {', '.join(nc.replace('_', ' ') for nc in selected_num_cols)} {time_range} ({len(points)} time points)."

        return ChartSpec(
            type="line",
            title=f"Trend Over Time by {t_col.replace('_', ' ').title()}",
            x=AxisSpec(column=t_col, label=t_col.replace("_", " ").title()),
            y=y_specs,
            source_query=q_label,
            points=points,
            alt_text=alt_text,
        )

    # 5. 1 Categorical Column (distinct <= 30) + 1 Numeric Column -> Horizontal Bar Chart
    if categorical_cols and numeric_cols:
        c_col = categorical_cols[0]
        n_col = numeric_cols[0]
        c_idx = columns.index(c_col)
        n_idx = columns.index(n_col)

        distinct_cats = len(set(col_values[c_col]))
        if distinct_cats <= 30:
            # Sort descending by numeric value
            sorted_rows = sorted(
                enumerate(rows, start=1),
                key=lambda item: _to_float(item[1][n_idx]),
                reverse=True,
            )

            # Cap at top 20
            is_truncated = len(sorted_rows) > 20
            display_rows = sorted_rows[:20]

            points = []
            for r_idx, r in display_rows:
                points.append({
                    "row_id": f"{q_label}:R{r_idx}",
                    "x": str(r[c_idx]),
                    "y": _to_float(r[n_idx]),
                })

            top_item = points[0] if points else None
            low_item = points[-1] if points else None
            fmt = "currency" if any(k in n_col.lower() for k in ("sales", "revenue", "amount", "price")) else None

            top_val_str = _format_cell(top_item["y"], fmt, curr_sym) if top_item else "N/A"
            low_val_str = _format_cell(low_item["y"], fmt, curr_sym) if low_item else "N/A"

            alt_text = (
                f"Bar chart of {n_col.replace('_', ' ')} by {c_col.replace('_', ' ')}; "
                f"highest: {top_item['x']} ({top_val_str}), lowest: {low_item['x']} ({low_val_str})."
            )

            note = f"Displaying top 20 of {len(rows)} categories." if is_truncated else None

            return ChartSpec(
                type="horizontal_bar",
                title=f"{n_col.replace('_', ' ').title()} by {c_col.replace('_', ' ').title()}",
                x=AxisSpec(column=c_col, label=c_col.replace("_", " ").title()),
                y=[AxisSpec(column=n_col, label=n_col.replace("_", " ").title(), format=fmt)],
                source_query=q_label,
                points=points,
                truncated=is_truncated,
                note=note,
                alt_text=alt_text,
            )

    # 6. Fallback: Table only
    return ChartSpec(type="table", title="Result Data Table", source_query=q_label)
