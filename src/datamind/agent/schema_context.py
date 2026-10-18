"""Small, question-specific categorical examples from the active database."""

import re

from sqlglot import exp


def collect_schema_examples(model, question, adapter, guard, evidence):
    words = set(re.findall(r"[a-z]+", question.lower()))
    examples = {}
    attempts = 0
    for table in model.tables:
        for column in table.columns:
            # Do not sample free text, names, contacts, identifiers or all columns.
            if column.is_document or not any(t in column.type.upper() for t in ("CHAR", "TEXT", "STRING")):
                continue
            if not re.search(r"(status|priority|segment|category|type|mode|flag)(_|$)", column.name, re.I):
                continue
            tokens = set(re.findall(r"[a-z]+", (column.name + " " + column.description).lower()))
            if not words.intersection(tokens) or attempts >= 3:
                continue
            attempts += 1
            field = exp.column(column.name, quoted=not bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", column.name)))
            sql = exp.select(field).distinct().from_(exp.to_table(table.name)).where(field.copy().is_(exp.Null()).not_()).order_by(field.copy()).limit(3).sql(dialect=adapter.dialect)
            try:
                sql = guard.validate(sql)
                result = adapter.execute(sql)
                examples[f"{table.name}.{column.name}"] = [r[0] for r in result.rows[:3] if isinstance(r[0], str) and len(r[0]) <= 120]
                evidence.validation_queries.append({
                    "purpose": "Live schema examples (not exhaustive)", "sql": sql,
                    "query_id": result.query_id, "column": f"{table.name}.{column.name}",
                    "row_count": len(result.rows),
                })
            except Exception:
                # Optional context must never prevent execution against the schema.
                evidence.validation_queries.append({"purpose": "Live schema examples", "column": f"{table.name}.{column.name}", "status": "unavailable"})
    return examples
