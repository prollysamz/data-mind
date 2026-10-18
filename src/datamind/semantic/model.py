"""Semantic model definitions for DataMind.

Defines tables, columns, metrics, join relationships, currency, and verified queries.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field


class ColumnDef(BaseModel):
    name: str
    type: str
    description: str = ""
    unit: str = ""
    is_primary_key: bool = False
    nullable: bool = True
    is_document: bool = False


class DefaultFilterDef(BaseModel):
    """A business filter queries on this table should apply unless the question says otherwise,
    e.g. column=order_status, values=[delivered]."""
    column: str
    values: list[str] = Field(default_factory=list)
    description: str = ""
    # Question words that mean the default does not apply (e.g. other status values).
    # Mentioning the column's own name parts (e.g. "status") always exempts.
    exempt_terms: list[str] = Field(default_factory=list)


class TableDef(BaseModel):
    name: str
    description: str = ""
    columns: list[ColumnDef] = Field(default_factory=list)
    primary_key: list[str] = Field(default_factory=list)
    default_filters: list[DefaultFilterDef] = Field(default_factory=list)

    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    def key_columns(self) -> set[str]:
        """Declared primary key (table-level list, else column flags), lowercased."""
        keys = self.primary_key or [c.name for c in self.columns if c.is_primary_key]
        return {k.lower() for k in keys}


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
    # Optional explicit cardinality from from_table to to_table:
    # "many_to_one" | "one_to_many" | "one_to_one". Inferred from primary keys when empty.
    relationship: str = ""

    def column_pairs(self) -> list[tuple[str, str]]:
        """(from_table column, to_table column) pairs from 'a.x = b.y [AND ...]' conditions."""
        pairs = []
        for left_t, left_c, right_t, right_c in re.findall(
            r"([\w\"]+)\.([\w\"]+)\s*=\s*([\w\"]+)\.([\w\"]+)", self.on_condition
        ):
            left_t, right_t = left_t.strip('"').lower(), right_t.strip('"').lower()
            left_c, right_c = left_c.strip('"').lower(), right_c.strip('"').lower()
            if left_t == self.from_table.lower() and right_t == self.to_table.lower():
                pairs.append((left_c, right_c))
            elif left_t == self.to_table.lower() and right_t == self.from_table.lower():
                pairs.append((right_c, left_c))
        return pairs


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

    def one_to_many_joins(self) -> list[tuple[str, str, set[str]]]:
        """(parent_table, child_table, parent_join_columns) for every 1-to-many join.

        Uses JoinDef.relationship when declared; otherwise the side whose join columns form
        its table's declared primary key is the "one" side. Joins with no declared keys on
        either side cannot be classified and are skipped.
        """
        result: list[tuple[str, str, set[str]]] = []
        for j in self.joins:
            pairs = j.column_pairs()
            if not pairs:
                continue
            from_cols = {a for a, _ in pairs}
            to_cols = {b for _, b in pairs}
            rel = j.relationship.strip().lower()
            if not rel:
                from_t, to_t = self.get_table(j.from_table), self.get_table(j.to_table)
                from_unique = bool(from_t and from_t.key_columns() and from_t.key_columns() <= from_cols)
                to_unique = bool(to_t and to_t.key_columns() and to_t.key_columns() <= to_cols)
                if to_unique and not from_unique:
                    rel = "many_to_one"
                elif from_unique and not to_unique:
                    rel = "one_to_many"
            if rel == "many_to_one":
                result.append((j.to_table.lower(), j.from_table.lower(), to_cols))
            elif rel == "one_to_many":
                result.append((j.from_table.lower(), j.to_table.lower(), from_cols))
        return result

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
            for f in t.default_filters:
                vals = ", ".join(f"'{v}'" for v in f.values)
                lines.append(f"  Default filter: {f.column} IN ({vals}) unless the question asks otherwise")

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
