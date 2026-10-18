"""Structured query lane: compile a question straight to a declared metric's SQL.

When a question names exactly one metric that the semantic model already defines, and
adds no grouping, filtering or ranking of its own, the metric's own SQL answers it. The
lane returns that SQL instead of asking the model to write it.

Everything here is derived from the active semantic model. There are no dataset-specific
table names, column names or literals, so pointing DataMind at a different schema changes
what the lane can match. It is deliberately conservative: anything it is not certain about
returns None and goes to the model, which is the normal path.

Disabled by default (`agent.structured_query_lane`). Runs recorded with the lane enabled
measure the semantic model, not the model's SQL generation, and must say so (eval/HISTORY.md §E).
"""

from __future__ import annotations

import re
from typing import Any

from datamind.semantic.model import SemanticModel

# Words that say the question wants something the bare metric does not answer:
# a breakdown, a ranking, a comparison, or a subset.
_DISQUALIFIERS = {
    "by", "each", "per", "top", "bottom", "worst", "best", "highest", "lowest",
    "rank", "ranking", "ranked", "between", "versus", "vs", "which", "compare",
    "comparison", "breakdown", "split", "trend", "over", "where", "excluding",
    "without", "only", "since", "before", "after", "during",
}

# Parts of a metric name that carry no meaning on their own.
_STOP_PARTS = {"the", "a", "an", "of", "in", "and", "total", "all"}


def compile_structured_spec(spec: dict[str, Any], semantic_model: SemanticModel) -> str | None:
    """Compile {metric, dimensions, filters, order, limit} into SQL for a declared metric."""
    metric = semantic_model.get_metric(spec.get("metric") or "")
    if not metric:
        return None

    dimensions = list(spec.get("dimensions") or [])
    filters = list(spec.get("filters") or [])
    order = "ASC" if str(spec.get("order", "DESC")).upper() == "ASC" else "DESC"
    limit = spec.get("limit")

    # A metric may ship its own canonical SQL; it is only valid unqualified.
    if metric.sql_template and not dimensions and not filters:
        return metric.sql_template.strip().rstrip(";") + ";"

    if not metric.table or not metric.expression:
        return None

    # Only dimensions the metric itself declares may be grouped on.
    allowed = {d.lower() for d in metric.dimensions}
    if any(d.split(".")[-1].lower() not in allowed for d in dimensions):
        return None

    selected = [*dimensions, f"{metric.expression} AS {metric.name}"]
    sql = f"SELECT {', '.join(selected)} FROM {metric.table}"
    if filters:
        sql += f" WHERE {' AND '.join(filters)}"
    if dimensions:
        sql += f" GROUP BY {', '.join(dimensions)} ORDER BY {metric.name} {order}"
    if limit is not None:
        try:
            sql += f" LIMIT {int(limit)}"
        except (TypeError, ValueError):
            return None
    return sql + ";"


def _names_a_value(question: str) -> bool:
    """True if the question pins down a particular value, so the unfiltered metric is wrong.

    Catches any number (a year, an id, an amount) and any quoted or capitalised literal,
    which is how a question names one product, region, status or period.
    """
    if re.search(r"\d", question) or re.search(r"[\"']", question):
        return True
    body = question.strip()
    # An all-caps token is a code: a state, currency, status or id (SP, USD, EUR).
    if re.search(r"\b[A-Z]{2,}\b", body):
        return True
    # A capitalised word mid-sentence usually names a product, region or status.
    return bool(re.search(r"(?<!^)(?<![.!?]\s)\b[A-Z][a-zA-Z]{2,}\b", body))


def try_structured_lane(question: str, semantic_model: SemanticModel) -> str | None:
    """Return SQL when the question maps cleanly onto one declared metric, else None.

    Requires a single unambiguous metric match: if two metrics match the wording, the
    question is not clear enough to answer without the model.
    """
    if not semantic_model or not semantic_model.metrics or not question.strip():
        return None

    words = set(re.findall(r"[a-z0-9]+", question.lower()))
    if words & _DISQUALIFIERS:
        return None
    if _names_a_value(question):
        return None

    matches = []
    for metric in semantic_model.metrics:
        parts = {p for p in metric.name.lower().split("_") if p and p not in _STOP_PARTS}
        if parts and parts <= words:
            matches.append(metric)

    if len(matches) != 1:
        return None
    return compile_structured_spec({"metric": matches[0].name}, semantic_model)
