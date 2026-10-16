"""Semantic model definitions for DataMind.

Defines tables, columns, metrics, join relationships, currency, and verified queries.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class ColumnDef(BaseModel):
    name: str
    type: str
    description: str = ""
    unit: str = ""
    is_primary_key: bool = False
    nullable: bool = True


class TableDef(BaseModel):
    name: str
    description: str = ""
    columns: list[ColumnDef] = Field(default_factory=list)
    primary_key: list[str] = Field(default_factory=list)

    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]


class MetricDef(BaseModel):
    name: str
    description: str = ""
    table: str
    expression: str
    unit: str = ""
    dimensions: list[str] = Field(default_factory=list)
    sql_template: str = ""


class JoinDef(BaseModel):
    from_table: str
    to_table: str
    on_condition: str
    join_type: str = "LEFT"


class VerifiedQuery(BaseModel):
    name: str
    question: str
    sql: str
    explanation: str = ""


class SemanticModel(BaseModel):
    name: str = "default"
    description: str = ""
    default_currency: str = "USD"
    currency_symbol: str = "$"
    tables: list[TableDef] = Field(default_factory=list)
    metrics: list[MetricDef] = Field(default_factory=list)
    joins: list[JoinDef] = Field(default_factory=list)
    verified_queries: list[VerifiedQuery] = Field(default_factory=list)

    def get_table(self, name: str) -> TableDef | None:
        target = name.strip().lower()
        for t in self.tables:
            if t.name.lower() == target:
                return t
        return None

    def get_approved_table_names(self) -> set[str]:
        """Return set of normalized (lowercase) table names allowed by this model."""
        return {t.name.strip().lower() for t in self.tables}

    def get_metric(self, name: str) -> MetricDef | None:
        target = name.strip().lower()
        for m in self.metrics:
            if m.name.lower() == target:
                return m
        return None

    def to_prompt_context(self) -> str:
        """Render a concise markdown description of tables, metrics, and joins for the LLM."""
        lines: list[str] = ["# Semantic Data Model\n"]
        lines.append(f"**Declared Currency:** {self.default_currency} ({self.currency_symbol})\n")
        lines.append("Note: `order_month` represents the starting date of the monthly period (YYYY-MM-01).\n")

        lines.append("## Approved Tables and Columns")
        for t in self.tables:
            cols_str = ", ".join(
                f"{c.name} ({c.type}{f', unit: {c.unit}' if c.unit else ''})"
                for c in t.columns
            )
            lines.append(f"- **{t.name}**: {t.description}")
            lines.append(f"  Columns: {cols_str}")

        if self.metrics:
            lines.append("\n## Business Metrics")
            for m in self.metrics:
                unit_str = f" [Unit: {m.unit}]" if m.unit else ""
                lines.append(f"- **{m.name}** ({m.table}){unit_str}: {m.description}")
                lines.append(f"  Formula: `{m.expression}`")
                if m.sql_template:
                    lines.append(f"  Reference SQL:\n```sql\n{m.sql_template.strip()}\n```")

        if self.joins:
            lines.append("\n## Approved Joins")
            for j in self.joins:
                lines.append(f"- {j.from_table} {j.join_type} JOIN {j.to_table} ON {j.on_condition}")

        if self.verified_queries:
            lines.append("\n## Verified Example Queries (Few-Shot Reference)")
            for vq in self.verified_queries:
                lines.append(f"- Question: {vq.question}")
                lines.append(f"```sql\n{vq.sql.strip()}\n```")

        return "\n".join(lines)
