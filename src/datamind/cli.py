"""DataMind command line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from datamind.adapters.duckdb_adapter import DuckDBAdapter
from datamind.agent.orchestrator import AgentOrchestrator
from datamind.config import load_config
from datamind.llm.client import LLMClient
from datamind.retrieval.sqlite_fts import SQLiteFTSRetriever
from datamind.semantic.loader import load_semantic_model


def handle_ask(args: argparse.Namespace) -> int:
    """Execute end-to-end question answering pipeline."""
    if not args.question:
        print("Error: No question provided. Usage: datamind ask \"<question>\"", file=sys.stderr)
        return 1

    config = load_config(args.config)
    semantic_model = load_semantic_model(config.semantic_model)

    # Initialize DuckDB adapter
    if config.backend.type == "duckdb":
        adapter = DuckDBAdapter(
            db_path=config.backend.duckdb_path,
            read_only=True,
            max_rows=config.guardrails.max_rows,
        )
    else:
        print(f"Error: Backend '{config.backend.type}' not yet configured for local CLI.", file=sys.stderr)
        return 1

    # Initialize and sync FTS retriever index
    retriever = SQLiteFTSRetriever(
        index_path=config.retrieval.index_path,
        source_db_path=config.backend.duckdb_path,
    )
    retriever.build_index()

    llm_client = LLMClient(config.llm)
    orchestrator = AgentOrchestrator(
        llm_client=llm_client,
        db_adapter=adapter,
        retriever=retriever,
        semantic_model=semantic_model,
    )

    try:
        result = orchestrator.run(args.question, max_turns=config.agent.max_steps)
    finally:
        adapter.close()
        retriever.close()

    if getattr(args, "json", False):
        output = {
            "question": result.question,
            "answer": result.answer,
            "success": result.success,
            "turns": result.turns,
            "error": result.error,
            "citations": {
                "is_clean": result.citation_report.is_clean,
                "valid_count": result.citation_report.valid_count,
                "invalid_count": result.citation_report.invalid_count,
                "items": [
                    {
                        "raw": c.raw,
                        "target_id": c.target_id,
                        "is_valid": c.is_valid,
                        "evidence_type": c.evidence_type,
                        "error": c.error,
                    }
                    for c in result.citation_report.citations
                ],
            },
            "evidence": result.evidence_store.to_json(),
        }
        print(json.dumps(output, indent=2, default=str))
        return 0 if result.success and result.citation_report.is_clean else 1

    # Terminal output
    print("=" * 70)
    print("DATAMIND ANSWER")
    print("=" * 70)
    print(f"\nQuestion: {result.question}\n")
    print("Response:")
    print(result.answer)
    print("\n" + "-" * 70)
    print("EVIDENCE & CITATION REPORT")
    print("-" * 70)
    print(f"Turns: {result.turns}")
    print(
        f"Citations: {result.citation_report.valid_count} valid, "
        f"{result.citation_report.invalid_count} invalid "
        f"({'PASS' if result.citation_report.is_clean else 'FAIL: Fabricated or Malformed Citations'})"
    )

    for c in result.citation_report.citations:
        status_icon = "[VALID]" if c.is_valid else "[FABRICATED/INVALID]"
        print(f"  {status_icon} {c.raw} ({c.evidence_type})")
        if c.error:
            print(f"      Error: {c.error}")

    if result.evidence_store.queries:
        print("\nExecuted SQL Queries:")
        for q in result.evidence_store.queries:
            print(f"  [{q.query_label}] (ID: {q.result.query_id}, Elapsed: {q.result.elapsed_ms:.1f}ms, Rows: {len(q.result.rows)})")
            print(f"      Purpose: {q.purpose}")
            print(f"      SQL: {q.sql.strip()}")

    if result.evidence_store.chunks:
        print(f"\nRetrieved Document Chunks ({len(result.evidence_store.chunks)}):")
        for chunk in result.evidence_store.chunks:
            print(f"  [{chunk.chunk_id}] {chunk.doc_name} (Score: {chunk.score})")

    print("=" * 70)
    return 0 if (result.success and result.citation_report.is_clean) else 1


def handle_index(args: argparse.Namespace) -> int:
    """Build or rebuild SQLite FTS search index."""
    config = load_config(args.config)
    print(f"Building FTS search index at '{config.retrieval.index_path}' from '{config.backend.duckdb_path}'...")
    retriever = SQLiteFTSRetriever(
        index_path=config.retrieval.index_path,
        source_db_path=config.backend.duckdb_path,
    )
    retriever.build_index()
    retriever.close()
    print("FTS index built successfully.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entrypoint for DataMind."""
    parser = argparse.ArgumentParser(
        prog="datamind",
        description="DataMind: Talk to Your Data with verifiable SQL and citations",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # init
    init_parser = subparsers.add_parser(
        "init",
        help="Introspect database schema and draft semantic model YAML",
    )
    init_parser.add_argument(
        "--accept",
        action="store_true",
        help="Accept drafted semantic model without interactive review",
    )

    # serve
    serve_parser = subparsers.add_parser(
        "serve",
        help="Start the DataMind API and UI server",
    )
    serve_parser.add_argument(
        "--config",
        default="datamind.yaml",
        help="Path to configuration YAML (default: datamind.yaml)",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind server (default: 8000)",
    )

    # ask
    ask_parser = subparsers.add_parser(
        "ask",
        help="Ask a natural language question against configured dataset",
    )
    ask_parser.add_argument(
        "question",
        nargs="?",
        default="",
        help="Natural language question to ask",
    )
    ask_parser.add_argument(
        "--config",
        default="datamind.yaml",
        help="Path to configuration YAML (default: datamind.yaml)",
    )
    ask_parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON with evidence provenance",
    )

    # eval
    eval_parser = subparsers.add_parser(
        "eval",
        help="Run evaluation benchmark suites (business, trust)",
    )
    eval_parser.add_argument(
        "--suite",
        choices=["all", "business", "trust"],
        default="all",
        help="Evaluation suite to run",
    )

    # index
    index_parser = subparsers.add_parser(
        "index",
        help="Build full-text search index for document tables",
    )
    index_parser.add_argument(
        "--config",
        default="datamind.yaml",
        help="Path to configuration YAML (default: datamind.yaml)",
    )

    args = parser.parse_args(argv)

    if not args.subcommand:
        parser.print_help()
        return 0

    if args.subcommand == "ask":
        return handle_ask(args)

    if args.subcommand == "index":
        return handle_index(args)

    if args.subcommand in {"init", "serve", "eval"}:
        print(f"Command '{args.subcommand}' is not implemented yet.")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
