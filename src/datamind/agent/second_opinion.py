"""Cross-model Second Opinion engine for verifiable AI query consensus and discrepancy auditing."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from datamind.adapters.base import DBAdapter, QueryResult
from datamind.guardrails.query_lint import AssumptionsCard, QueryLinter
from datamind.guardrails.sql_guard import SQLGuard, SQLSecurityError

logger = logging.getLogger(__name__)


@dataclass
class AssumptionsDiff:
    tables_diff: list[str] = field(default_factory=list)
    filters_diff: list[str] = field(default_factory=list)
    metrics_diff: list[str] = field(default_factory=list)
    group_by_diff: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SecondOpinionResult:
    verdict: str  # "AGREE_EXACT", "AGREE_VALUE", "DISAGREE", "ERROR"
    verdict_label: str
    primary_model: str
    secondary_model: str
    primary_sql: str
    secondary_sql: str
    primary_row_count: int = 0
    secondary_row_count: int = 0
    primary_sample_rows: list[dict[str, Any]] = field(default_factory=list)
    secondary_sample_rows: list[dict[str, Any]] = field(default_factory=list)
    assumptions_diff: AssumptionsDiff = field(default_factory=AssumptionsDiff)
    primary_assumptions: dict[str, Any] = field(default_factory=dict)
    secondary_assumptions: dict[str, Any] = field(default_factory=dict)
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "verdict_label": self.verdict_label,
            "primary_model": self.primary_model,
            "secondary_model": self.secondary_model,
            "primary_sql": self.primary_sql,
            "secondary_sql": self.secondary_sql,
            "primary_row_count": self.primary_row_count,
            "secondary_row_count": self.secondary_row_count,
            "primary_sample_rows": self.primary_sample_rows,
            "secondary_sample_rows": self.secondary_sample_rows,
            "assumptions_diff": self.assumptions_diff.to_dict(),
            "primary_assumptions": self.primary_assumptions,
            "secondary_assumptions": self.secondary_assumptions,
            "explanation": self.explanation,
        }


def compare_result_sets(res1: QueryResult, res2: QueryResult) -> tuple[str, str]:
    """Compare two QueryResult instances for exact match, value match, or disagreement."""
    if not res1.rows and not res2.rows:
        return "AGREE_EXACT", "Both models returned 0 rows (agreed empty result)."

    if len(res1.rows) != len(res2.rows):
        return "DISAGREE", f"Row count mismatch: Primary returned {len(res1.rows)} rows, Secondary returned {len(res2.rows)} rows."

    # Compare exact rows
    if res1.rows == res2.rows:
        return "AGREE_EXACT", "Both models generated queries producing identical result sets."

    # Compare flattened values sets
    def extract_values(rows: Sequence[Sequence[Any]]) -> set[Any]:
        vals = set()
        for r in rows:
            for cell in r:
                if cell is not None:
                    # Round floats to 2 decimal places for comparison
                    try:
                        f = round(float(cell), 2)
                        vals.add(f)
                    except (ValueError, TypeError):
                        vals.add(str(cell).strip().lower())
        return vals

    vals1 = extract_values(res1.rows)
    vals2 = extract_values(res2.rows)

    if vals1 == vals2:
        return "AGREE_VALUE", "Models produced different query structure but identical numeric values."

    common = vals1.intersection(vals2)
    diff = vals1.symmetric_difference(vals2)
    return "DISAGREE", f"Result values diverge: {len(common)} common values, {len(diff)} mismatched values."


def diff_assumptions(card1: AssumptionsCard, card2: AssumptionsCard) -> AssumptionsDiff:
    """Calculate AST assumptions difference between two queries."""
    tables1 = set(getattr(card1, "tables", []))
    tables2 = set(getattr(card2, "tables", []))
    filters1 = set(getattr(card1, "filters", []))
    filters2 = set(getattr(card2, "filters", []))
    metrics1 = set(getattr(card1, "metric_expressions", getattr(card1, "metrics", [])))
    metrics2 = set(getattr(card2, "metric_expressions", getattr(card2, "metrics", [])))
    group1 = set(getattr(card1, "grouping", getattr(card1, "group_by", [])))
    group2 = set(getattr(card2, "grouping", getattr(card2, "group_by", [])))

    return AssumptionsDiff(
        tables_diff=sorted(tables1.symmetric_difference(tables2)),
        filters_diff=sorted(filters1.symmetric_difference(filters2)),
        metrics_diff=sorted(metrics1.symmetric_difference(metrics2)),
        group_by_diff=sorted(group1.symmetric_difference(group2)),
    )


class SecondOpinionEngine:
    """Orchestrates independent second opinion query generation and cross-model comparison."""

    def __init__(self, adapter: DBAdapter, guard: SQLGuard, linter: QueryLinter | None = None) -> None:
        self.adapter = adapter
        self.guard = guard
        self.linter = linter or QueryLinter()

    def evaluate_queries(
        self,
        primary_sql: str,
        secondary_sql: str,
        *,
        primary_model: str = "primary",
        secondary_model: str = "secondary",
    ) -> SecondOpinionResult:
        """Execute and compare two distinct SQL queries for the same user question."""
        # 1. AST Linting and Assumptions compilation
        _, p_card = self.linter.lint_query(primary_sql)
        _, s_card = self.linter.lint_query(secondary_sql)
        assumptions_diff = diff_assumptions(p_card, s_card)

        # 2. Guard validation
        try:
            p_clean = self.guard.validate(primary_sql)
            s_clean = self.guard.validate(secondary_sql)
        except SQLSecurityError as exc:
            return SecondOpinionResult(
                verdict="ERROR",
                verdict_label="SQL Security Rejected",
                primary_model=primary_model,
                secondary_model=secondary_model,
                primary_sql=primary_sql,
                secondary_sql=secondary_sql,
                explanation=f"Query rejected by security guard: {exc}",
            )

        # 3. Execution
        try:
            p_res = self.adapter.execute(p_clean)
            s_res = self.adapter.execute(s_clean)
        except Exception as exc:
            return SecondOpinionResult(
                verdict="ERROR",
                verdict_label="Execution Failed",
                primary_model=primary_model,
                secondary_model=secondary_model,
                primary_sql=primary_sql,
                secondary_sql=secondary_sql,
                explanation=f"Database execution error: {exc}",
            )

        # 4. Result set comparison
        verdict, explanation = compare_result_sets(p_res, s_res)

        p_sample = [dict(zip(p_res.columns, row, strict=False)) for row in p_res.rows[:5]]
        s_sample = [dict(zip(s_res.columns, row, strict=False)) for row in s_res.rows[:5]]

        labels = {
            "AGREE_EXACT": "Consensus (Identical Results)",
            "AGREE_VALUE": "Consensus (Same Values, Different Shape)",
            "DISAGREE": "Models Disagree (Assumptions Diverged)",
        }

        return SecondOpinionResult(
            verdict=verdict,
            verdict_label=labels.get(verdict, verdict),
            primary_model=primary_model,
            secondary_model=secondary_model,
            primary_sql=primary_sql,
            secondary_sql=secondary_sql,
            primary_row_count=len(p_res.rows),
            secondary_row_count=len(s_res.rows),
            primary_sample_rows=p_sample,
            secondary_sample_rows=s_sample,
            assumptions_diff=assumptions_diff,
            primary_assumptions=p_card.to_dict(),
            secondary_assumptions=s_card.to_dict(),
            explanation=explanation,
        )
