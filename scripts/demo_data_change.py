"""Demonstrate that DataMind's answer follows the data: ask, change the data, ask again.

The same question is answered twice by the agent. Between the two runs one sales line is
inserted, and afterwards it is removed again, so the dataset is left as it was.

  DuckDB (default): works on a temporary copy of the configured database file.
  Snowflake:        inserts with the DATAMIND_LOADER role, queries with the configured
                    read-only role, prints Snowflake query IDs for both runs, then deletes the row.

Usage:
  python scripts/demo_data_change.py                              # datamind.yaml (DuckDB)
  python scripts/demo_data_change.py datamind_snowflake.yaml      # Snowflake
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from datamind.adapters import backend_label, build_adapter
from datamind.agent.orchestrator import AgentOrchestrator
from datamind.config import AppConfig, load_config
from datamind.llm.client import LLMClient
from datamind.retrieval.sqlite_fts import SQLiteFTSRetriever
from datamind.semantic.loader import load_semantic_model

QUESTION = "What was the total sales revenue for CloudSync in May 2026?"
MARKER_ORDER_ID = 990001
INSERT_SQL = f"""
INSERT INTO SALES (order_id, line_no, order_date, order_month, product_id, product_name, quantity, amount)
SELECT {MARKER_ORDER_ID}, 1, DATE '2026-05-15', DATE '2026-05-01', product_id, product_name, 100, 50000.00
FROM SALES WHERE product_name = 'CloudSync' LIMIT 1
"""
DELETE_SQL = f"DELETE FROM SALES WHERE order_id = {MARKER_ORDER_ID}"


def ask(config: AppConfig, label: str) -> None:
    adapter = build_adapter(config)
    retriever = SQLiteFTSRetriever(index_path=":memory:")
    orchestrator = AgentOrchestrator(
        llm_client=LLMClient(config.llm),
        db_adapter=adapter,
        retriever=retriever,
        semantic_model=load_semantic_model(config.semantic_model),
    )
    try:
        result = orchestrator.run(QUESTION, max_turns=config.agent.max_steps)
    finally:
        adapter.close()
        retriever.close()
    print(f"\n=== {label} ===")
    print(result.answer)
    for q in result.evidence_store.queries:
        print(f"  [{q.query_label}] query_id={q.result.query_id}  rows={q.result.rows[:3]}")
        print(f"      {q.sql}")
    print(f"  citations clean: {result.citation_report.is_clean}")


def run_duckdb(config: AppConfig) -> int:
    import duckdb

    with tempfile.TemporaryDirectory() as tmp:
        copy_path = Path(tmp) / "demo_copy.duckdb"
        shutil.copy(config.backend.duckdb_path, copy_path)
        config.backend.duckdb_path = str(copy_path)
        print(f"Working on a temporary copy: {copy_path}")

        ask(config, "BEFORE the data change")
        with duckdb.connect(str(copy_path)) as conn:
            conn.execute(INSERT_SQL)
        print(f"\n>>> Inserted one CloudSync sales line of $50,000.00 (order_id {MARKER_ORDER_ID}) for May 2026")
        ask(config, "AFTER the data change")
    return 0


def run_snowflake(config: AppConfig) -> int:
    import snowflake.connector

    sf = config.backend.snowflake
    writer = snowflake.connector.connect(
        account=sf.get_account(),
        user=sf.get_user(),
        password=sf.get_password(),
        role="DATAMIND_LOADER",
        warehouse=sf.warehouse,
        database=sf.database,
        schema=sf.schema,
    )
    try:
        cur = writer.cursor()
        cur.execute(DELETE_SQL)  # clean up any leftover row from an interrupted run
        ask(config, "BEFORE the data change")
        cur.execute(INSERT_SQL)
        print(f"\n>>> Inserted one CloudSync sales line of $50,000.00 (order_id {MARKER_ORDER_ID}), "
              f"Snowflake query_id={cur.sfqid}")
        ask(config, "AFTER the data change")
    finally:
        cur = writer.cursor()
        cur.execute(DELETE_SQL)
        print(f"\n>>> Removed the inserted row again (query_id={cur.sfqid})")
        writer.close()
    return 0


def main() -> int:
    config_path = sys.argv[1] if len(sys.argv) > 1 else "datamind.yaml"
    config = load_config(config_path)
    print(f"Backend: {backend_label(config)} | Model: {config.llm.orchestrator_model}")
    print(f"Question: {QUESTION}")
    if config.backend.type == "snowflake":
        return run_snowflake(config)
    return run_duckdb(config)


if __name__ == "__main__":
    sys.exit(main())
