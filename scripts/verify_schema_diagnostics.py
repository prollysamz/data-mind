"""Live Snowflake checks for enriched context and empty date-filter diagnostics.

No model answers or source records are mocked. Only metadata, coverage aggregates
and execution receipts are saved; no TPC-H record rows or example values are saved.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from datamind.adapters import build_adapter
from datamind.agent.evidence import EvidenceStore
from datamind.agent.schema_context import collect_schema_examples
from datamind.agent.tools import execute_sql_tool
from datamind.agent.verifier import verify_citations
from datamind.config import load_config
from datamind.guardrails.sql_guard import SQLGuard
from datamind.semantic.loader import load_semantic_model


def verify():
    config = load_config("datamind_tpch.yaml")
    config.backend.snowflake.query_tag = "datamind:verification:schema-diagnostics"
    model = load_semantic_model(config.semantic_model)
    store = EvidenceStore()
    guard = SQLGuard(model.get_approved_table_names(), dialect="snowflake")
    with build_adapter(config) as adapter:
        examples = collect_schema_examples(model, "How many orders have urgent priority?", adapter, guard, store)
        prompt = model.to_prompt_context(examples)
        if not examples.get("ORDERS.O_ORDERPRIORITY") or "Primary key: O_ORDERKEY" not in prompt:
            raise RuntimeError("Schema examples or primary key were not available")
        execute_sql_tool("SELECT O_ORDERKEY FROM ORDERS WHERE O_ORDERDATE >= DATE '2030-01-01'", "Empty date range verification", guard, adapter, store, model)
        if store.queries[0].result.rows or not store.diagnostics or store.diagnostics[0]["status"] != "available":
            raise RuntimeError("Expected an empty result with a separate coverage receipt")
        execution_report = verify_citations("The executed query returned no matching rows [[Q1:EXEC]].", store, model)
        fabricated_report = verify_citations("No matching rows [[Q1:R1]].", store, model)
        if not execution_report.is_clean or fabricated_report.is_clean:
            raise RuntimeError("Empty execution provenance must resolve without inventing a result row")
    return {
        "timestamp": datetime.now(UTC).isoformat(), "status": "PASS", "backend": "snowflake",
        "schema_example_columns": list(examples), "validation_queries": store.validation_queries,
        "queries": [{"sql": q.sql, "query_id": q.result.query_id, "kind": q.kind, "row_count": len(q.result.rows)} for q in store.queries],
        "diagnostics": store.diagnostics,
        "execution_citation_check": {"citation": "Q1:EXEC", "valid": execution_report.is_clean,
                                     "fabricated_row_rejected": not fabricated_report.is_clean},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="eval/evidence/schema_diagnostics_snowflake.json")
    args = parser.parse_args()
    report = verify()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
