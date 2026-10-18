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
import uuid
from pathlib import Path

from datamind.adapters import backend_label, build_adapter
from datamind.agent.orchestrator import AgentOrchestrator, AgentResult
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


def ask(config: AppConfig, label: str) -> AgentResult:
    adapter = build_adapter(config)
    retriever = SQLiteFTSRetriever(index_path=":memory:")
    orchestrator = AgentOrchestrator(
        llm_client=LLMClient(config.llm),
        db_adapter=adapter,
        retriever=retriever,
        semantic_model=load_semantic_model(config.semantic_model),
        config=config.agent,
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
    return result


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
    from datamind.eval.runner import _compare_result_sets
    from datamind.uploads.snowflake_store import SnowflakeUploadStore, identifier

    sf = config.backend.snowflake
    # Work exclusively in a newly created schema. Never delete a fixed marker ID
    # or insert into the user's source SALES table.
    schema = "DATAMIND_CHANGE_" + uuid.uuid4().hex[:12].upper()
    database = identifier(sf.database or "DATAMIND")
    namespace = f"{database}.{identifier(schema)}"
    original = f"{database}.{identifier(sf.schema or 'PUBLIC')}.{identifier('SALES')}"
    target = f"{namespace}.{identifier('SALES')}"
    writer_adapter = SnowflakeUploadStore(config)._loader()
    writer = writer_adapter._conn
    created = False
    try:
        cur = writer.cursor()
        cur.execute(f"CREATE SCHEMA {namespace}")
        created = True
        cur.execute(f"CREATE TABLE {target} CLONE {original}")
        cur.execute(f"ALTER TABLE {target} SET DATA_RETENTION_TIME_IN_DAYS = 1")
        cur.execute(f"GRANT USAGE ON SCHEMA {namespace} TO ROLE {identifier(sf.role)}")
        cur.execute(f"GRANT SELECT ON TABLE {target} TO ROLE {identifier(sf.role)}")
        cur.execute(f"USE SCHEMA {namespace}")
        config = config.model_copy(deep=True)
        config.backend.snowflake.schema_ = schema
        config.backend.snowflake.query_tag = "datamind:data-change:" + schema
        baseline_sql = "SELECT SUM(AMOUNT) FROM SALES WHERE PRODUCT_NAME = 'CloudSync' AND ORDER_MONTH = DATE '2026-05-01'"
        cur.execute(baseline_sql)
        before = cur.fetchone()[0]
        print(f"Baseline sum={before}; query_id={cur.sfqid}")
        first_answer = ask(config, "BEFORE the data change")
        if not first_answer.success or not first_answer.citation_report.is_clean or not _compare_result_sets([(before,)], first_answer.evidence_store.queries)[0]:
            raise RuntimeError("The before answer did not match the independent live aggregate")
        cur.execute(INSERT_SQL)
        insertion_id = cur.sfqid
        if cur.rowcount != 1:
            raise RuntimeError("Expected exactly one inserted row in isolated demo")
        writer.commit()
        print(f"\n>>> Inserted one CloudSync sales line of $50,000.00 (order_id {MARKER_ORDER_ID}), "
              f"Snowflake query_id={insertion_id}")
        cur.execute(baseline_sql)
        after = cur.fetchone()[0]
        print(f"Changed sum={after}; query_id={cur.sfqid}")
        if before is None or after - before != 50000:
            raise RuntimeError("Live Snowflake aggregate did not increase by exactly 50000")
        second_answer = ask(config, "AFTER the data change")
        if not second_answer.success or not second_answer.citation_report.is_clean or not _compare_result_sets([(after,)], second_answer.evidence_store.queries)[0]:
            raise RuntimeError("The after answer did not match the independent live aggregate")
        cur.execute(baseline_sql.replace("FROM SALES", f"FROM SALES BEFORE (STATEMENT => '{insertion_id}')"))
        historical = cur.fetchone()[0]
        print(f"Time Travel sum={historical}; anchor={insertion_id}; query_id={cur.sfqid}")
        if historical != before:
            raise RuntimeError("Time Travel did not recover the original aggregate")
    finally:
        try:
            if created:
                cur = writer.cursor()
                cur.execute(f"DROP SCHEMA {namespace} CASCADE")
                print(f"\n>>> Removed isolated demo schema {schema} (query_id={cur.sfqid})")
        finally:
            writer_adapter.close()
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
