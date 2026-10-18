"""Deterministic Query Linter and Assumptions Card Engine for DataMind.

Analyzes executed SQL queries against the Semantic Model AST to catch
"verified but wrong" semantic issues:
1. Join Fan-Out: Multiplied row counts when aggregating across 1-to-many joins without DISTINCT.
2. Default-Filter Echo: Missing declared business filters (e.g. order_status = 'delivered').
3. Empty or Null-Heavy Results: Zero rows returned or >50% null values.
4. Row-Limit Truncation: Results truncated by limit ceiling.
5. Unrequested Grouping: GROUP BY on a dimension the question never mentions
   (e.g. per-product rows for "total revenue for each month").

Checks 1 and 2 take their rules from the semantic model: 1-to-many pairs from its joins
(explicit `relationship`, or inferred from declared primary keys) and filters from `default_filters`
declared on tables. A linter built without a model skips them.

Downgrades verification badge to "Partially verified" with plain-language diagnostic reasons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any
import sqlglot
from sqlglot import exp

from datamind.semantic.model import SemanticModel


@dataclass
class QueryLintFinding:
    check_name: str
    severity: str  # "WARNING" | "ERROR"
    message: str
    remediation: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "check_name": self.check_name,
            "severity": self.severity,
            "message": self.message,
            "remediation": self.remediation,
        }


@dataclass
class AssumptionsCard:
    tables: list[str] = field(default_factory=list)
    join_keys: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    grouping: list[str] = field(default_factory=list)
    metric_expressions: list[str] = field(default_factory=list)
    date_range: list[str] = field(default_factory=list)
    row_limit: int | None = None
    is_truncated: bool = False
    lint_findings: list[QueryLintFinding] = field(default_factory=list)
    badge_status: str = "VERIFIED"  # "VERIFIED" | "PARTIALLY_VERIFIED" | "UNVERIFIED"
    badge_reason: str = "All numbers match cited rows with zero query lint warnings."
    model_written_summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tables": self.tables,
            "join_keys": self.join_keys,
            "filters": self.filters,
            "grouping": self.grouping,
            "metric_expressions": self.metric_expressions,
            "date_range": self.date_range,
            "row_limit": self.row_limit,
            "is_truncated": self.is_truncated,
            "badge_status": self.badge_status,
            "badge_reason": self.badge_reason,
            "lint_findings": [f.to_dict() for f in self.lint_findings],
            "model_written_summary": self.model_written_summary,
        }

    def to_markdown(self) -> str:
        """Render Assumptions Card as an elegant markdown card for UI and reports."""
        badge_icon = "🟢" if self.badge_status == "VERIFIED" else ("🟡" if self.badge_status == "PARTIALLY_VERIFIED" else "🔴")
        lines = [
            f"#### {badge_icon} Assumptions & Query Verification Card: `{self.badge_status.replace('_', ' ')}`",
            f"> **Status Reason:** {self.badge_reason}",
            "",
            f"- **Tables Queried:** {', '.join(f'`{t}`' for t in self.tables) if self.tables else 'None'}",
        ]
        if self.join_keys:
            lines.append(f"- **Join Keys:** {', '.join(f'`{k}`' for k in self.join_keys)}")
        if self.filters:
            lines.append(f"- **Filters Applied:** {', '.join(f'`{f}`' for f in self.filters)}")
        if self.grouping:
            lines.append(f"- **Grouped By:** {', '.join(f'`{g}`' for g in self.grouping)}")
        if self.metric_expressions:
            lines.append(f"- **Metrics Aggregated:** {', '.join(f'`{m}`' for m in self.metric_expressions)}")
        if self.date_range:
            lines.append(f"- **Date Constraints:** {', '.join(f'`{d}`' for d in self.date_range)}")
        if self.row_limit is not None:
            trunc_str = " (Result Truncated)" if self.is_truncated else " (Clean limit)"
            lines.append(f"- **Row Limit:** `{self.row_limit}`{trunc_str}")

        if self.lint_findings:
            lines.append("\n**⚠️ Query Lint Warnings:**")
            for f in self.lint_findings:
                lines.append(f"- **[{f.check_name}]** {f.message}")

        return "\n".join(lines)


# Column-name parts that say nothing about which dimension a user asked for
_GENERIC_COLUMN_PARTS = {"name", "id", "date", "at", "no", "num", "number", "key", "code", "value", "dt", "ts"}


def _question_mentions(part: str, question_words: set[str]) -> bool:
    """True if a column-name part (e.g. 'product', 'month', 'category') appears in the question."""
    forms = {part, part + "s", part + "es", part + "ly"}
    if part.endswith("y"):
        forms.add(part[:-1] + "ies")
    if forms & question_words:
        return True
    for w in question_words:
        stem = w[:-1] if w.endswith("s") else w
        # "monthly" for month; "invoice" for invoiceno, "customers" for customerid
        if (len(part) >= 4 and w.startswith(part)) or (len(stem) >= 5 and part.startswith(stem)):
            return True
    return False


def unrequested_group_columns(group_columns: list[str], question: str) -> list[str]:
    """Return GROUP BY columns whose meaningful name parts never appear in the question."""
    question_words = set(re.findall(r"[a-z0-9]+", question.lower()))
    flagged = []
    for col in group_columns:
        bare = col.split(".")[-1].strip('"').lower()
        parts = [p for p in re.split(r"[^a-z0-9]+", bare) if p]
        if all(p in _GENERIC_COLUMN_PARTS for p in parts):
            continue  # nothing specific enough to judge
        if not any(_question_mentions(p, question_words) for p in parts):
            flagged.append(col)
    return flagged


class QueryLinter:
    """Deterministic SQL AST linter inspecting fan-out, missing filters, and result integrity."""

    def __init__(self, semantic_model: SemanticModel | None = None) -> None:
        self.semantic_model = semantic_model

    def lint_query(
        self,
        sql: str,
        question: str = "",
        result_rows: list[Any] | None = None,
        max_rows_limit: int = 1000,
    ) -> tuple[list[QueryLintFinding], AssumptionsCard]:
        """Perform comprehensive deterministic lint checks against SQL AST and result set."""
        findings: list[QueryLintFinding] = []
        clean_sql = sql.strip().rstrip(";")

        # Fallback if SQL is empty
        if not clean_sql:
            return findings, AssumptionsCard(badge_status="UNVERIFIED", badge_reason="No SQL query was executed.")

        try:
            ast = sqlglot.parse_one(clean_sql)
        except Exception:
            try:
                ast = sqlglot.parse_one(clean_sql, read="duckdb")
            except Exception as e:
                findings.append(
                    QueryLintFinding(
                        check_name="sql_parse_error",
                        severity="WARNING",
                        message=f"Could not parse SQL AST: {e}",
                    )
                )
                return findings, AssumptionsCard(
                    lint_findings=findings,
                    badge_status="PARTIALLY_VERIFIED",
                    badge_reason="SQL syntax could not be parsed for AST verification.",
                )

        # 1. Extract AST components
        tables = [t.name.lower() for t in ast.find_all(exp.Table) if t.name]
        tables = list(dict.fromkeys(t for t in tables if t not in ("dual", "subquery")))

        join_keys: list[str] = []
        for j in ast.find_all(exp.Join):
            on_clause = j.args.get("on")
            if on_clause:
                join_keys.append(on_clause.sql())

        filters: list[str] = []
        where_node = ast.find(exp.Where)
        if where_node:
            filters.append(where_node.this.sql())

        grouping: list[str] = []
        group_node = ast.find(exp.Group)
        if group_node:
            for g in group_node.expressions:
                grouping.append(g.sql())

        metric_expressions: list[str] = []
        for agg in ast.find_all((exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max)):
            metric_expressions.append(agg.sql())

        date_range: list[str] = []
        where_sql_lower = where_node.sql().lower() if where_node else ""
        year_matches = re.findall(r"\b(201[5-9]|202[0-9])\b", where_sql_lower)
        if year_matches:
            date_range.extend([f"Year {y}" for y in sorted(set(year_matches))])
        if "between" in where_sql_lower or ">" in where_sql_lower or "<" in where_sql_lower:
            date_cols = {"date"} | {
                c.name.lower()
                for t in (self.semantic_model.tables if self.semantic_model else [])
                for c in t.columns
                if re.search(r"date|time", c.type.lower())
            }
            date_alt = "|".join(re.escape(c) for c in sorted(date_cols, key=len, reverse=True))
            for part in re.findall(rf"(?:{date_alt})\s*(?:between|[><=]+)\s*[^)\n]+", where_sql_lower):
                date_range.append(part.strip())

        limit_val: int | None = None
        limit_node = ast.find(exp.Limit)
        if limit_node and limit_node.expression:
            try:
                limit_val = int(limit_node.expression.sql())
            except ValueError:
                pass

        # ----------------------------------------------------------------------
        # Check A: Join Fan-Out Detection
        # ----------------------------------------------------------------------
        one_to_many = self.semantic_model.one_to_many_joins() if self.semantic_model else []

        for parent, child, parent_keys in one_to_many:
            if parent in tables and child in tables:
                for agg in ast.find_all((exp.Count, exp.Sum)):
                    agg_sql = agg.sql().lower()
                    is_distinct = isinstance(agg.this, exp.Distinct) if hasattr(agg, "this") else False
                    is_parent_key = any(re.search(rf"\b{re.escape(k)}\b", agg_sql) for k in parent_keys)

                    if is_parent_key and not is_distinct:
                        findings.append(
                            QueryLintFinding(
                                check_name="join_fan_out",
                                severity="WARNING",
                                message=(
                                    f"Join fan-out detected: Aggregation '{agg.sql()}' across 1-to-many join "
                                    f"between '{parent}' and '{child}' lacks DISTINCT, which multiplies row counts."
                                ),
                                remediation=f"Use COUNT(DISTINCT {agg.this.sql() if hasattr(agg, 'this') else '...'}) to prevent row multiplication.",
                            )
                        )

        # ----------------------------------------------------------------------
        # Check B: Default-Filter Echo Check
        # ----------------------------------------------------------------------
        q_lower = question.lower()
        q_words = set(re.findall(r"[a-z0-9]+", q_lower))
        for table_def in (self.semantic_model.tables if self.semantic_model else []):
            if table_def.name.lower() not in tables:
                continue
            for dflt in table_def.default_filters:
                column = dflt.column.lower()
                # Asking about the filter column itself ("by status") or a declared exemption lifts the default
                # (only parts that don't just repeat the table name: 'order' in olist_orders.order_status)
                table_parts = set(re.split(r"[^a-z0-9]+", table_def.name.lower()))
                name_parts = {
                    p for p in re.split(r"[^a-z0-9]+", column)
                    if p and p not in _GENERIC_COLUMN_PARTS and not _question_mentions(p, table_parts)
                }
                if any(_question_mentions(p, q_words) for p in name_parts) or any(
                    t.lower() in q_lower for t in dflt.exempt_terms
                ):
                    continue
                values = [v.lower() for v in dflt.values]
                if column in where_sql_lower and (not values or any(v in where_sql_lower for v in values)):
                    continue
                wanted = " / ".join(f"'{v}'" for v in dflt.values) or "its declared default"
                findings.append(
                    QueryLintFinding(
                        check_name="missing_default_filter",
                        severity="WARNING",
                        message=(
                            f"Default filter missing: Query includes '{table_def.name}' but does not filter for "
                            f"{dflt.column} = {wanted}. {dflt.description}"
                        ).strip(),
                        remediation=f"Add WHERE {dflt.column} = {wanted} in accordance with semantic model defaults.",
                    )
                )

        # ----------------------------------------------------------------------
        # Check C: Empty or Null-Heavy Results
        # ----------------------------------------------------------------------
        is_truncated = False
        if result_rows is not None:
            if len(result_rows) == 0:
                findings.append(
                    QueryLintFinding(
                        check_name="empty_result",
                        severity="WARNING",
                        message="Query execution returned 0 rows from the database.",
                        remediation="Verify join conditions and filter criteria.",
                    )
                )
            else:
                total_cells = sum(len(r) for r in result_rows) if result_rows else 0
                null_cells = sum(sum(1 for c in r if c is None) for r in result_rows) if result_rows else 0
                if total_cells > 0 and (null_cells / total_cells) > 0.50:
                    findings.append(
                        QueryLintFinding(
                            check_name="null_heavy_result",
                            severity="WARNING",
                            message=f"Null-heavy result: {null_cells}/{total_cells} ({round(null_cells/total_cells*100, 1)}%) of values are NULL.",
                            remediation="Inspect column nullability and outer joins.",
                        )
                    )

            # Check D: Row-Limit Truncation
            if limit_val is not None and len(result_rows) == limit_val and limit_val >= 10:
                is_truncated = True
                findings.append(
                    QueryLintFinding(
                        check_name="row_limit_truncation",
                        severity="WARNING",
                        message=f"Row-limit reached: Query returned exactly {limit_val} rows (limit ceiling reached).",
                        remediation="Increase LIMIT or apply more specific filtering.",
                    )
                )

        # ----------------------------------------------------------------------
        # Check E: Unrequested Grouping Dimension
        # ----------------------------------------------------------------------
        # Prefer the outermost query's GROUP BY; fall back to the first one (e.g. inside a CTE).
        top_group = ast.args.get("group") if isinstance(ast, exp.Select) else None
        grain_columns = [g.sql() for g in top_group.expressions] if top_group else grouping
        group_columns = [c for c in grain_columns if re.fullmatch(r'[\w."]+', c)]
        if question.strip():
            for col in unrequested_group_columns(group_columns, question):
                findings.append(
                    QueryLintFinding(
                        check_name="unrequested_grouping",
                        severity="WARNING",
                        message=(
                            f"The query groups by '{col}', which the question does not ask for, so the rows "
                            f"may be a breakdown rather than the requested total."
                        ),
                        remediation=f"Remove '{col}' from GROUP BY unless a per-{col.split('.')[-1]} breakdown was intended.",
                    )
                )

        # ----------------------------------------------------------------------
        # Build Assumptions Card & Determine Downgraded Badge
        # ----------------------------------------------------------------------
        if findings:
            badge_status = "PARTIALLY_VERIFIED"
            first_msg = findings[0].message
            badge_reason = f"Partially verified: {first_msg}"
        else:
            badge_status = "VERIFIED"
            badge_reason = "Verified: SQL AST adheres to semantic model join constraints and default filters."

        card = AssumptionsCard(
            tables=tables,
            join_keys=join_keys,
            filters=filters,
            grouping=grouping,
            metric_expressions=metric_expressions,
            date_range=date_range,
            row_limit=limit_val,
            is_truncated=is_truncated,
            lint_findings=findings,
            badge_status=badge_status,
            badge_reason=badge_reason,
        )

        return findings, card
