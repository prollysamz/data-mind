"""Schema pruning technique for small models.

Dynamically filters semantic model tables to include only tables relevant to the
user's question based on keyword matching, descriptions, and foreign key relations.
"""

from __future__ import annotations

import re
from typing import Any
from datamind.semantic.model import SemanticModel, TableDef, JoinDef


_STOP_WORDS = {
    "a", "an", "the", "in", "on", "at", "for", "to", "of", "and", "or", "is",
    "was", "are", "were", "what", "which", "who", "whom", "how", "our", "all",
    "by", "with", "from", "as", "that", "this", "overall",
}


def prune_semantic_model(model: SemanticModel, question: str, max_tables: int = 3) -> SemanticModel:
    """Filter tables in semantic model to only those relevant to user question."""
    q_tokens = {
        t for t in re.findall(r"\b[a-z0-9_]+\b", question.lower())
        if t not in _STOP_WORDS
    }

    # Score each table
    table_scores: dict[str, float] = {}
    for table in model.tables:
        score = 0.0
        # Table name match
        t_tokens = set(re.findall(r"\b[a-z0-9_]+\b", table.name.lower()))
        score += len(q_tokens & t_tokens) * 3.0

        # Column names match (strong signal)
        for col in table.columns:
            c_tokens = set(re.findall(r"\b[a-z0-9_]+\b", col.name.lower()))
            score += len(q_tokens & c_tokens) * 2.0

        # Description match (weak signal)
        d_tokens = set(re.findall(r"\b[a-z0-9_]+\b", table.description.lower()))
        score += len(q_tokens & d_tokens) * 0.5

        table_scores[table.name] = score

    # Select top scoring tables
    ranked_tables = [t for t, s in sorted(table_scores.items(), key=lambda x: x[1], reverse=True) if s > 0]
    selected_tables = set(ranked_tables[:max_tables])

    # If no tables matched specifically, keep all
    if not selected_tables:
        return model

    # Add connected join tables if needed
    for join in model.joins:
        if join.from_table in selected_tables:
            selected_tables.add(join.to_table)
        elif join.to_table in selected_tables and len(selected_tables) < max_tables:
            selected_tables.add(join.from_table)

    pruned_tables = [t for t in model.tables if t.name in selected_tables]
    pruned_joins = [
        j for j in model.joins
        if j.from_table in selected_tables and j.to_table in selected_tables
    ]

    return SemanticModel(
        name=f"{model.name}_pruned",
        description=model.description,
        default_currency=model.default_currency,
        currency_symbol=model.currency_symbol,
        tables=pruned_tables,
        metrics=model.metrics,
        joins=pruned_joins,
        verified_queries=model.verified_queries,
    )
