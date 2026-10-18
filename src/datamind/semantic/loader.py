"""Semantic model loader from YAML files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from datamind.semantic.model import (
    ColumnDef,
    DefaultFilterDef,
    JoinDef,
    MetricDef,
    SemanticModel,
    TableDef,
    VerifiedQuery,
)


def load_semantic_model(yaml_path: str | Path) -> SemanticModel:
    """Load and validate semantic model YAML."""
    path = Path(yaml_path)
    if not path.is_file():
        raise FileNotFoundError(f"Semantic model file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    tables: list[TableDef] = []
    for t_data in data.get("tables", []):
        cols = [ColumnDef(**c) for c in t_data.get("columns", [])]
        tables.append(
            TableDef(
                name=t_data["name"],
                description=t_data.get("description", ""),
                columns=cols,
                primary_key=t_data.get("primary_key", []),
                default_filters=[DefaultFilterDef(**f) for f in t_data.get("default_filters", [])],
            )
        )

    metrics: list[MetricDef] = [
        MetricDef(**m) for m in data.get("metrics", [])
    ]

    joins: list[JoinDef] = [
        JoinDef(**j) for j in data.get("joins", [])
    ]

    verified_queries: list[VerifiedQuery] = [
        VerifiedQuery(**vq) for vq in data.get("verified_queries", [])
    ]

    return SemanticModel(
        name=data.get("name", path.stem),
        description=data.get("description", ""),
        default_currency=data.get("default_currency", "USD"),
        currency_symbol=data.get("currency_symbol", "$"),
        tables=tables,
        metrics=metrics,
        joins=joins,
        verified_queries=verified_queries,
    )
