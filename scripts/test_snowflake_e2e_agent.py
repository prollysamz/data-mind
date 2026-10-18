"""Live end-to-end check: ask Gemma a question that is answered by SQL running in Snowflake.

Prerequisites: scripts/snowflake_bootstrap.sql and scripts/setup_snowflake_demo.sql have been
run, SNOWFLAKE_ACCOUNT / SNOWFLAKE_USER / SNOWFLAKE_PASSWORD are set (e.g. in .env), and the
local Gemma model is running. Prints the answer plus every Snowflake query ID so the run can be
matched against QUERY_HISTORY in Snowsight.

Usage: python scripts/test_snowflake_e2e_agent.py [config] ["question"]
"""

from __future__ import annotations

import sys

from datamind.adapters import backend_label, build_adapter
from datamind.agent.orchestrator import AgentOrchestrator
from datamind.config import load_config
from datamind.llm.client import LLMClient
from datamind.retrieval.sqlite_fts import SQLiteFTSRetriever
from datamind.semantic.loader import load_semantic_model


def main() -> int:
    config_path = sys.argv[1] if len(sys.argv) > 1 else "datamind_snowflake.yaml"
    question = sys.argv[2] if len(sys.argv) > 2 else "What was the total sales revenue for each product?"

    config = load_config(config_path)
    if config.backend.type != "snowflake":
        print(f"Error: {config_path} does not select the Snowflake backend.", file=sys.stderr)
        return 1

    adapter = build_adapter(config)
    retriever = SQLiteFTSRetriever(
        index_path=config.retrieval.index_path,
        source_db_path=config.retrieval_source_path(),
    )
    retriever.build_index()
    orchestrator = AgentOrchestrator(
        llm_client=LLMClient(config.llm),
        db_adapter=adapter,
        retriever=retriever,
        semantic_model=load_semantic_model(config.semantic_model),
    )

    print(f"Backend: {backend_label(config)}")
    print(f"Model:   {config.llm.orchestrator_model}")
    print(f"Question: {question}\n")
    try:
        result = orchestrator.run(question, max_turns=config.agent.max_steps)
    finally:
        adapter.close()
        retriever.close()

    print("ANSWER:")
    print(result.answer)
    print("\nSNOWFLAKE QUERIES:")
    for q in result.evidence_store.queries:
        query_id = q.result.query_id if q.result else "n/a"
        print(f"  {q.query_label}  query_id={query_id}")
        print(f"    {q.sql}")
    report = result.citation_report
    print(f"\nCitations clean: {report.is_clean} | verified numbers: {report.verified_numbers_count}")
    return 0 if result.success and result.evidence_store.queries else 1


if __name__ == "__main__":
    sys.exit(main())
