"""Narrow, independently cited date-coverage context for empty SQL results."""

import json

import sqlglot
from sqlglot import exp


def empty_execution_receipt(evidence):
    """Narrow fallback for one complete, empty answer query, without invented rows."""
    queries = [q for q in evidence.queries if q.kind != "diagnostic"]
    if len(queries) != 1 or evidence.chunks:
        return None
    query = queries[0]
    if query.result.rows or query.result.truncated:
        return None
    return (
        "The model's explanation did not pass verification. "
        f"The executed query returned no matching rows [[{query.query_label}:EXEC]]. "
        "This does not establish a measured zero or explain why no rows matched. "
        "Inspect the SQL filters and any separate source-coverage diagnostic."
    )


def diagnose_date_coverage(sql, source_label, result, model, guard, adapter, evidence):
    tree = sqlglot.parse_one(sql, read=adapter.dialect)
    null_aggregate = len(result.rows) == 1 and bool(result.rows[0]) and all(v is None for v in result.rows[0]) and any(tree.find_all(exp.AggFunc))
    if result.rows and not null_aggregate:
        return ""
    # Deliberately skip joins, CTEs, subqueries and set operations: a source-table
    # range cannot explain the effect of their joins and filters.
    if not isinstance(tree, exp.Select) or len(list(tree.find_all(exp.Select))) != 1 or tree.args.get("joins"):
        return ""
    tables = list(tree.find_all(exp.Table))
    if len(tables) != 1 or not tree.args.get("where"):
        return ""
    source = tables[0]
    table = model.get_table(source.name)
    if table is None:
        return ""
    columns = {c.name.lower(): c for c in table.columns if "DATE" in c.type.upper() or "TIMESTAMP" in c.type.upper()}
    relevant = {c.name.lower() for c in tree.args["where"].find_all(exp.Column)
                if c.name.lower() in columns and (not c.table or c.table.lower() == source.alias_or_name.lower())}
    if len(relevant) != 1:
        return ""
    column = columns[relevant.pop()]
    reference = next(c for c in tree.args["where"].find_all(exp.Column) if c.name.lower() == column.name.lower())
    field = exp.Column(this=reference.this.copy())
    base_table = source.copy()
    base_table.set("alias", None)
    statement = exp.select(
        exp.alias_(exp.Min(this=field.copy()), "earliest_date"),
        exp.alias_(exp.Max(this=field.copy()), "latest_date"),
        exp.alias_(exp.Count(this=exp.Star()), "source_rows"),
        exp.alias_(exp.Count(this=field.copy()), "dated_rows"),
    ).from_(base_table)
    # The original source has no filters here. Say so explicitly in both evidence
    # and UI, and never substitute these counts for the requested metric.
    diagnostic = {"source_query": source_label, "table": table.name, "column": column.name,
                  "scope": "Whole source table; original filters excluded",
                  "trigger": "null_aggregate" if null_aggregate else "empty_rows"}
    try:
        statement_sql = guard.validate(statement.sql(dialect=adapter.dialect))
        coverage = adapter.execute(statement_sql)
        label = evidence.add_query(statement_sql, f"Date coverage diagnostic for {source_label}: whole source table, original filters excluded", coverage, kind="diagnostic")
        low, high, total, dated = coverage.rows[0]
        diagnostic.update(status="available", query_label=label, query_id=coverage.query_id,
                          earliest_date=low, latest_date=high, source_rows=total, dated_rows=dated)
    except Exception:
        diagnostic.update(status="unavailable")
    evidence.diagnostics.append(diagnostic)
    return "\nDate coverage diagnostic (separate context, not the requested answer): " + json.dumps(diagnostic, default=str) + (
        f". Cite [[{diagnostic['query_label']}:R1]] for this coverage. No single cause for the empty result has been established."
        if diagnostic["status"] == "available" else ". Coverage could not be checked; do not infer a cause."
    )
