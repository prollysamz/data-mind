"""DataMind command line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence
import yaml

from datamind.adapters.duckdb_adapter import DuckDBAdapter
from datamind.adapters.snowflake_adapter import SnowflakeAdapter
from datamind.agent.orchestrator import AgentOrchestrator
from datamind.config import load_config, load_dotenv
from datamind.eval.runner import run_evaluation
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

    # Backend selection (CLI flag overrides config)
    backend_type = getattr(args, "backend", None) or config.backend.type

    if backend_type == "duckdb":
        adapter = DuckDBAdapter(
            db_path=config.backend.duckdb_path,
            read_only=True,
            max_rows=config.guardrails.max_rows,
        )
    elif backend_type == "snowflake":
        adapter = SnowflakeAdapter(
            config=config.backend.snowflake,
            max_rows=config.guardrails.max_rows,
            timeout_seconds=config.guardrails.statement_timeout_seconds,
        )
    else:
        print(f"Error: Unknown backend '{backend_type}'.", file=sys.stderr)
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

    is_permissive = getattr(args, "permissive", False)
    is_strict = not is_permissive
    is_success = result.success and (result.citation_report.is_clean if is_strict else True)

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
                "verified_numbers_count": result.citation_report.verified_numbers_count,
                "discrepancies_count": result.citation_report.discrepancy_count,
                "unsupported_claims_count": result.citation_report.unsupported_claims_count,
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
                "numeric_checks": [
                    {
                        "raw_text": nc.raw_text,
                        "claimed_value": nc.claimed_value,
                        "status": nc.status,
                        "row_id": nc.row_id,
                        "matched_column": nc.matched_column,
                        "cell_value": nc.cell_value,
                        "message": nc.message,
                    }
                    for nc in result.citation_report.numeric_checks
                ],
            },
            "evidence": result.evidence_store.to_json(),
        }
        print(json.dumps(output, indent=2, default=str))
        return 0 if is_success else 1

    # Terminal output
    print("=" * 70)
    print("DATAMIND ANSWER")
    print("=" * 70)
    print(f"\nQuestion: {result.question}\n")
    print("Response:")
    print(result.answer)
    print("\n" + "-" * 70)
    print("EVIDENCE & DETERMINISTIC VERIFICATION REPORT")
    print("-" * 70)
    print(f"Turns: {result.turns}")
    print(
        f"Citations: {result.citation_report.valid_count} valid, "
        f"{result.citation_report.invalid_count} invalid "
        f"({'PASS' if result.citation_report.invalid_count == 0 else 'FAIL: Fabricated Citations'})"
    )
    print(
        f"Numeric Checks: {result.citation_report.verified_numbers_count} verified, "
        f"{result.citation_report.discrepancy_count} discrepancies, "
        f"{result.citation_report.unsupported_claims_count} unsupported claims"
    )

    for c in result.citation_report.citations:
        status_icon = "[VALID]" if c.is_valid else "[FABRICATED/INVALID]"
        print(f"  {status_icon} {c.raw} ({c.evidence_type})")
        if c.error:
            print(f"      Error: {c.error}")

    if result.citation_report.numeric_checks:
        print("\nNumeric Consistency Details:")
        for nc in result.citation_report.numeric_checks:
            badge = f"[{nc.status}]"
            print(f"  {badge} {nc.message}")

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
    return 0 if is_success else 1


def handle_usage(args: argparse.Namespace) -> int:
    """Print or reset LLM API and token usage tracking."""
    from datamind.llm.budget import CostGuard
    config = load_config(getattr(args, "config", "datamind.yaml"))
    guard = CostGuard()

    if getattr(args, "reset", False):
        confirm = input("Are you sure you want to reset all persistent usage history? [y/N]: ").strip().lower()
        if confirm in ("y", "yes"):
            guard.reset_usage()
            print("Usage history reset successfully.")
            return 0
        else:
            print("Usage reset cancelled.")
            return 0

    max_usd = config.llm.budget.max_usd_total
    summary = guard.get_usage_summary(max_usd_total=max_usd)

    print("=" * 70)
    print("DATAMIND METERED USAGE AND BUDGET REPORT")
    print("=" * 70)
    print(f"Total API Calls:            {summary.total_calls}")
    print(f"Total Prompt Tokens:        {summary.total_prompt_tokens:,}")
    print(f"Total Completion Tokens:    {summary.total_completion_tokens:,}")
    print(f"Total Combined Tokens:      {(summary.total_prompt_tokens + summary.total_completion_tokens):,}")
    print(f"Total Estimated Spend:      ${summary.total_usd:.4f} USD")
    if summary.remaining_budget_usd is not None:
        print(f"Configured Budget Ceiling:  ${max_usd:.2f} USD")
        print(f"Remaining Budget:           ${summary.remaining_budget_usd:.4f} USD")
    else:
        print("Configured Budget Ceiling:  None (Unlimited or Local Only)")
    print("-" * 70)

    # By Day
    if summary.by_day:
        print("\nUsage By Day:")
        print(f"  {'Date':<12} {'Calls':<8} {'Tokens':<14} {'Estimated USD':<14}")
        print("  " + "-" * 50)
        for day, stats in sorted(summary.by_day.items()):
            tok_str = f"{stats['tokens']:,}"
            print(f"  {day:<12} {stats['calls']:<8} {tok_str:<14} ${stats['usd']:<13.4f}")

    # By Model
    if summary.by_model:
        print("\nUsage By Model:")
        print(f"  {'Model':<24} {'Calls':<8} {'Tokens':<14} {'Estimated USD':<14}")
        print("  " + "-" * 62)
        for model, stats in sorted(summary.by_model.items()):
            tok_str = f"{stats['tokens']:,}"
            print(f"  {model:<24} {stats['calls']:<8} {tok_str:<14} ${stats['usd']:<13.4f}")

    # By Purpose
    if summary.by_purpose:
        print("\nUsage By Purpose:")
        print(f"  {'Purpose':<14} {'Calls':<8} {'Tokens':<14} {'Estimated USD':<14}")
        print("  " + "-" * 50)
        for purpose, stats in sorted(summary.by_purpose.items()):
            tok_str = f"{stats['tokens']:,}"
            print(f"  {purpose:<14} {stats['calls']:<8} {tok_str:<14} ${stats['usd']:<13.4f}")

    print("=" * 70)
    return 0


def handle_warehouse_suspend(args: argparse.Namespace) -> int:
    """Suspend Snowflake warehouse immediately to prevent idle cloud compute spend."""
    config = load_config(getattr(args, "config", "datamind.yaml"))
    wh = config.backend.snowflake.warehouse if config.backend.snowflake else "DATAMIND_XS"
    print(f"Suspending Snowflake warehouse '{wh}'...")
    try:
        from datamind.adapters.snowflake_adapter import SnowflakeAdapter
        adapter = SnowflakeAdapter(config=config.backend.snowflake)
        adapter.execute(f"ALTER WAREHOUSE {wh} SUSPEND;")
        adapter.close()
        print(f"Successfully suspended warehouse '{wh}'. Idle spend prevented.")
        return 0
    except Exception as e:
        print(f"Notice / Error suspending warehouse: {e}", file=sys.stderr)
        print(f"SQL for manual suspension in worksheet: ALTER WAREHOUSE {wh} SUSPEND;")
        return 1


def handle_eval(args: argparse.Namespace) -> int:
    """Run benchmark evaluation suites."""
    config = load_config(args.config)
    provider = getattr(args, "provider", "local")
    use_cache = getattr(args, "cache", None)
    if use_cache is None:
        # Default on for cloud eval, off otherwise
        use_cache = (provider == "cloud")

    print("=" * 70)
    print(f"DATAMIND EVALUATION RUNNER — Suite: {args.suite.upper()} | Provider: {provider.upper()}")
    print("=" * 70)

    if args.suite == "verifier":
        if str(Path.cwd()) not in sys.path:
            sys.path.insert(0, str(Path.cwd()))
        from eval.mutation import run_mutation_suite, run_false_positive_suite, print_mutation_report
        print("Running Deterministic Verifier Mutation and False-Positive Suite...")
        m_res = run_mutation_suite()
        fp_res = run_false_positive_suite()
        report_md = print_mutation_report(m_res, fp_res)
        print("\n" + report_md + "\n")
        return 0 if (m_res.missed_count == 0 and fp_res["false_positives"] == 0) else 1

    if args.suite == "security":
        print("Running Comprehensive Security Test Suite...")
        import pytest
        ret = pytest.main(["-q", "tests/test_security.py"])
        return int(ret)

    # Cloud evaluation safety checks
    if provider == "cloud":
        from datamind.llm.budget import CostGuard
        guard = CostGuard()
        max_usd = config.llm.budget.max_usd_total or 10.0
        summary = guard.get_usage_summary(max_usd_total=max_usd)

        # Estimate cost: approx questions x 3 turns x 2000 tokens
        est_questions = 21 if args.suite in ("all", "business") else 10
        est_tokens = est_questions * 3 * 2000
        p_in = (config.llm.budget.price_per_million_input_usd or 0.0) / 1_000_000.0
        p_out = (config.llm.budget.price_per_million_output_usd or 0.0) / 1_000_000.0
        est_cost = (est_tokens * 0.7 * p_in) + (est_tokens * 0.3 * p_out)

        print("Cloud Evaluation Cost Estimate:")
        print(f"  Estimated Questions:     {est_questions}")
        print(f"  Projected Tokens:        ~{est_tokens:,} tokens")
        print(f"  Projected Cost:          ~${est_cost:.4f} USD")
        print(f"  Configured Budget Cap:   ${max_usd:.2f} USD")
        print(f"  Current Spend:           ${summary.total_usd:.4f} USD")
        print(f"  Remaining Budget:        ${(summary.remaining_budget_usd or 0.0):.4f} USD")
        print(f"  Response Cache:          {'ENABLED' if use_cache else 'DISABLED'}")
        print("-" * 70)

        if not getattr(args, "yes", False):
            confirm = input("Proceed with cloud evaluation run? [y/N]: ").strip().lower()
            if confirm not in ("y", "yes"):
                print("Evaluation aborted by user.")
                return 0

    print("Executing benchmark questions against configured model and database...")
    report = run_evaluation(
        suite=args.suite,
        config_path=args.config,
        provider=provider,
        use_cache=use_cache,
    )

    print("\n" + "-" * 70)
    summary_str = f"EVALUATION SUMMARY: {report.passed} / {report.total} Passed ({report.pass_rate_pct}% Pass Rate)"
    if report.not_run > 0:
        summary_str += f" [{report.not_run} Not Run]"
    print(summary_str)
    print("-" * 70)
    for item in report.items:
        badge = f"[{item.status}]" if hasattr(item, "status") else ("[PASS]" if item.passed else "[FAIL]")
        print(f"  {badge:<10} {item.item_id:<22} ({item.suite:<8}) {item.reason}")

    print("\nResults report generated at: eval/results/RESULTS.md")
    print("=" * 70)
    return 0 if report.failed == 0 and report.not_run == 0 else 1


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


def handle_check_leakage(args: argparse.Namespace) -> int:
    """Run leakage guard verifying semantic model verified queries are disjoint from questions."""
    from datamind.eval.leakage_guard import check_model_leakage

    model_path = getattr(args, "model", "examples/olist/semantic_model.yaml")
    questions_path = getattr(args, "questions", "eval/questions/olist_dev.yaml")
    threshold = getattr(args, "threshold", 0.80)

    print("=" * 70)
    print("DATAMIND ZERO-LEAKAGE GUARD REPORT")
    print("=" * 70)
    print(f"Semantic Model: {model_path}")
    print(f"Question Set:   {questions_path}")
    print(f"Threshold:      {threshold}")

    rep = check_model_leakage(model_path, questions_path, threshold=threshold)
    print(f"Pairs Evaluated: {rep.pairs_evaluated}")
    print(f"Max Similarity:  {rep.max_similarity:.4f}")
    print(f"Violations:      {len(rep.violations)}")
    print(f"Status:          {'PASS (Zero Leakage Verified)' if rep.passed else 'FAIL (Leakage Detected)'}")
    print("-" * 70)
    print("Top Closest Pairs:")
    for idx, p in enumerate(rep.top_matches, 1):
        print(f"  {idx}. [{p.similarity:.4f}] Training: '{p.training_question[:40]}...' vs {p.eval_id}: '{p.eval_question[:40]}...'")
    print("=" * 70)

    if getattr(args, "output_json", None):
        import json
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump({
                "model_path": rep.semantic_model_path,
                "questions_path": rep.question_set_path,
                "threshold": rep.threshold,
                "max_similarity": rep.max_similarity,
                "passed": rep.passed,
                "violations_count": len(rep.violations),
                "top_matches": [
                    {
                        "eval_id": p.eval_id,
                        "similarity": p.similarity,
                        "training_question": p.training_question,
                        "eval_question": p.eval_question,
                    }
                    for p in rep.top_matches
                ]
            }, f, indent=2)
        print(f"Saved JSON report to {args.output_json}")

    return 0 if rep.passed else 1


def handle_serve(args: argparse.Namespace) -> int:
    """Start DataMind UI and API HTTP server."""
    from datamind.server import start_server

    backend = getattr(args, "backend", None)
    port = getattr(args, "port", 8000)
    host = getattr(args, "host", "127.0.0.1")
    config_path = getattr(args, "config", "datamind.yaml")
    enable_uploads = getattr(args, "enable_uploads", False)
    keep_uploads = getattr(args, "keep_uploads", False)

    start_server(
        config_path=config_path,
        backend=backend,
        host=host,
        port=port,
        enable_uploads=enable_uploads,
        keep_uploads=keep_uploads,
    )
    return 0


def handle_demo(args: argparse.Namespace) -> int:
    """Run diagnostics, display demo overview and suggested questions, and launch interactive web server."""
    from datamind.doctor import run_diagnostics, print_doctor_report
    config_path = getattr(args, "config", "datamind_olist.yaml")
    if not Path(config_path).exists():
        config_path = "datamind.yaml"

    print("Checking system prerequisites...")
    checks = run_diagnostics(config_path=config_path)
    failed = [c for c in checks if not c.passed]
    if failed:
        print("\nDiagnostic check failed. Please resolve the following before running demo:")
        print_doctor_report(checks)
        return 1

    config = load_config(config_path)
    semantic_model = load_semantic_model(config.semantic_model)

    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8080)

    print("\n" + "=" * 70)
    print("DATAMIND ONE-COMMAND DEMO RUNNER")
    print("=" * 70)
    print(f"Active Semantic Model: {semantic_model.name} ({len(semantic_model.tables)} tables)")
    print(f"Active Backend:        {config.backend.type.upper()}")
    print(f"Server URL:            http://{host}:{port}")
    print("\nSuggested Questions for This Dataset:")
    if "olist" in semantic_model.name.lower():
        print("  1. Which product categories generated the highest net sales revenue?")
        print("  2. What is the late delivery rate and what were customer reviews about delayed orders?")
        print("  3. What was the month-over-month revenue trend for delivered orders?")
    else:
        print("  1. Which products experienced the largest month-over-month revenue decline?")
        print("  2. What were customer complaints about Novaship?")
        print("  3. What is the average order value across all quarters?")
    print("=" * 70)
    print(f"\nStarting interactive web server at http://{host}:{port}...\n")

    from datamind.server.server import start_server
    start_server(
        config_path=config_path,
        host=host,
        port=port,
        enable_uploads=True,
    )
    return 0


def handle_init(args: argparse.Namespace) -> int:
    """Introspect schema and auto-generate semantic_model.yaml and datamind configuration."""
    db_path = getattr(args, "db", None) or "examples/primary/demo.duckdb"
    out_path = Path(getattr(args, "output", None) or "semantic_model.yaml")

    if not Path(db_path).exists():
        print(f"Error: Database file '{db_path}' not found.", file=sys.stderr)
        return 1

    import duckdb
    con = duckdb.connect(db_path, read_only=True)
    try:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        schema_tables = []
        for t in tables:
            desc = con.execute(f"DESCRIBE {t}").fetchall()
            cols = []
            for c in desc:
                col_name = c[0]
                col_type = c[1]
                cols.append({
                    "name": col_name,
                    "type": col_type,
                    "description": f"{col_name} ({col_type}) auto-introspected from schema",
                })
            schema_tables.append({
                "name": t,
                "description": f"Table {t} containing {len(cols)} columns auto-introspected by datamind init",
                "columns": cols,
            })
    finally:
        con.close()

    model_data = {
        "name": Path(db_path).stem,
        "description": f"Auto-generated semantic model for {db_path} created via datamind init.",
        "default_currency": "USD",
        "currency_symbol": "$",
        "tables": schema_tables,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.dump(model_data, f, sort_keys=False)

    print(f"Successfully introspected {len(tables)} tables ({', '.join(tables)}) from '{db_path}'.")
    return 0


def handle_models(args: argparse.Namespace) -> int:
    """List or probe models registered in DataMind."""
    from datamind.llm.models import ModelRegistry
    registry = ModelRegistry()
    action = getattr(args, "action", "list") or "list"

    if action == "list":
        models = registry.list_models()
        print("\n========================= DATAMIND MODEL REGISTRY =========================")
        print(f"{'ID':<26} {'LABEL':<28} {'PRIVACY':<15} {'STATUS':<15} {'CAPABILITIES'}")
        print("-" * 105)
        for m in models:
            caps = ", ".join(f"{k}" for k, v in m.capabilities.items() if v)
            print(f"{m.id:<26} {m.label:<28} {m.privacy_class:<15} {m.status:<15} {caps}")
        print("-" * 105)
        print("Available Presets: local, hybrid_privacy, cloud_accuracy, second_opinion\n")
        return 0

    if action == "test":
        target = getattr(args, "model_id", None)
        if not target:
            print("Error: Specify model ID to test. Usage: datamind models test <model_id>", file=sys.stderr)
            return 1
        model_info = registry.get_model(target)
        if not model_info:
            print(f"Error: Unknown model ID '{target}'.", file=sys.stderr)
            return 1
        print(f"Testing model '{target}' ({model_info.label})...")
        if model_info.status != "ready":
            print(f"[FAIL] Model status is '{model_info.status}': {model_info.status_reason}")
            return 1
        from datamind.llm.client import LLMClient
        from datamind.config import load_config
        config = load_config()
        client = LLMClient(config.llm, purpose="test")
        try:
            resp = client.chat(
                [{"role": "user", "content": "Return 'OK' if operational."}],
                model=target,
                max_tokens=50,
            )
            ans = resp.get("content", "")
            print(f"[PASS] Model test successful! Response: {ans.strip()[:60]}")
            return 0
        except Exception as exc:
            print(f"[FAIL] Model test failed: {exc}")
            return 1

    return 0


def handle_verify_receipt(args: argparse.Namespace) -> int:
    """Verify cryptographic receipt hash chain and replay SQL against database."""
    from datamind.trust.receipts import ReceiptVerifier
    path = Path(args.receipt_file)
    if not path.exists():
        print(f"Error: Receipt file '{path}' not found.", file=sys.stderr)
        return 1

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"\n================ VERIFYING CRYPTOGRAPHIC RECEIPT: {path.name} ================")
    res = ReceiptVerifier.verify(data)
    print(f"Root Hash: {res.get('root_hash')}")
    print("Component Integrity Checks:")
    for check_name, passed in res.get("checks", {}).items():
        sym = "[PASS]" if passed else "[FAIL]"
        print(f"  {sym} {check_name}")
    print(f"Overall Result: {res.get('status')}")

    if getattr(args, "replay", False):
        print("\nReplaying SQL queries against active database backend to detect data drift...")
        from datamind.config import load_config
        from datamind.guardrails.sql_guard import SQLGuard
        config = load_config()
        if config.backend.type == "duckdb":
            from datamind.adapters.duckdb_adapter import DuckDBAdapter
            adapter = DuckDBAdapter(config.backend.duckdb_path, read_only=True)
        else:
            from datamind.adapters.snowflake_adapter import SnowflakeAdapter
            adapter = SnowflakeAdapter(config.backend.snowflake)
        guard = SQLGuard(approved_tables=set(adapter.list_tables()))
        try:
            replay_res = ReceiptVerifier.replay(data, adapter, guard)
            print(f"Replay Result: {replay_res.get('status')}")
            for f in replay_res.get("findings", []):
                print(f"  - SQL: {f.get('sql')[:60]}... -> {f.get('status')}")
        finally:
            adapter.close()

    return 0 if res.get("verified") else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entrypoint for DataMind."""
    load_dotenv()
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
        "--db",
        default="examples/primary/demo.duckdb",
        help="Path to database to introspect (default: examples/primary/demo.duckdb)",
    )
    init_parser.add_argument(
        "--output",
        default="semantic_model.yaml",
        help="Path to write semantic model YAML (default: semantic_model.yaml)",
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
    serve_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address to bind server (default: 127.0.0.1)",
    )
    serve_parser.add_argument(
        "--backend",
        choices=["duckdb", "snowflake"],
        default=None,
        help="Database backend to query (default: from config)",
    )
    serve_parser.add_argument(
        "--enable-uploads",
        action="store_true",
        help="Enable user-uploaded datasets endpoint and UI",
    )
    serve_parser.add_argument(
        "--keep-uploads",
        action="store_true",
        help="Keep uploaded datasets on server shutdown instead of deleting",
    )

    # ask / run
    ask_parser = subparsers.add_parser(
        "ask",
        aliases=["run"],
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
        "--backend",
        choices=["duckdb", "snowflake"],
        default=None,
        help="Database backend to query (default: from config)",
    )
    ask_parser.add_argument(
        "--permissive",
        action="store_true",
        help="Permissive mode: do not exit with error on numeric discrepancies or unsupported claims (strict mode is default)",
    )
    ask_parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON with evidence provenance and numeric verification",
    )

    # eval
    eval_parser = subparsers.add_parser(
        "eval",
        help="Run evaluation benchmark suites (business, trust)",
    )
    eval_parser.add_argument(
        "--suite",
        choices=["all", "business", "trust", "held_out", "held_out_fresh", "held_out_sealed", "verifier", "security", "real_data", "olist_dev"],
        default="all",
        help="Evaluation suite to run",
    )
    eval_parser.add_argument(
        "--config",
        default="datamind.yaml",
        help="Path to configuration YAML (default: datamind.yaml)",
    )
    eval_parser.add_argument(
        "--ablation",
        action="store_true",
        help="Run technique ablation suite on dev set and generate ablation table",
    )
    eval_parser.add_argument(
        "--provider",
        choices=["local", "cloud"],
        default="local",
        help="LLM provider: local (Ollama/vLLM) or cloud (fail-closed, metered)",
    )
    eval_parser.add_argument(
        "--cache",
        action="store_true",
        default=None,
        help="Enable persistent SQLite response cache (default on for cloud, off for local)",
    )
    eval_parser.add_argument(
        "--no-cache",
        dest="cache",
        action="store_false",
        help="Disable response cache",
    )
    eval_parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip interactive confirmation prompt for cloud evaluation",
    )

    # usage
    usage_parser = subparsers.add_parser(
        "usage",
        help="View metered token and dollar spend report",
    )
    usage_parser.add_argument(
        "--config",
        default="datamind.yaml",
        help="Path to configuration YAML (default: datamind.yaml)",
    )
    usage_parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset persistent usage data (requires confirmation)",
    )

    # warehouse-suspend
    suspend_parser = subparsers.add_parser(
        "warehouse-suspend",
        help="Suspend Snowflake warehouse to eliminate idle cloud compute spend",
    )
    suspend_parser.add_argument(
        "--config",
        default="datamind.yaml",
        help="Path to configuration YAML (default: datamind.yaml)",
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

    # doctor
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Run system diagnostics and verify dependencies, models, and adapters",
    )
    doctor_parser.add_argument(
        "--config",
        default="datamind.yaml",
        help="Path to configuration YAML (default: datamind.yaml)",
    )

    # mcp
    mcp_parser = subparsers.add_parser(
        "mcp",
        help="Run Model Context Protocol (MCP) server over stdio for IDE and agent integrations",
    )
    mcp_parser.add_argument(
        "--config",
        default="datamind.yaml",
        help="Path to configuration YAML (default: datamind.yaml)",
    )

    # demo
    demo_parser = subparsers.add_parser(
        "demo",
        help="One-command demo runner: check diagnostics and start interactive web UI",
    )
    demo_parser.add_argument(
        "--config",
        default="datamind_olist.yaml",
        help="Path to configuration YAML (default: datamind_olist.yaml)",
    )
    demo_parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port to bind server (default: 8080)",
    )
    demo_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address to bind server (default: 127.0.0.1)",
    )

    # check-leakage
    leakage_parser = subparsers.add_parser(
        "check-leakage",
        help="Verify training few-shots and eval questions are strictly disjoint (Leakage Guard)",
    )
    leakage_parser.add_argument(
        "--model",
        default="examples/olist/semantic_model.yaml",
        help="Path to semantic model YAML (default: examples/olist/semantic_model.yaml)",
    )
    leakage_parser.add_argument(
        "--questions",
        default="eval/questions/olist_dev.yaml",
        help="Path to question set YAML (default: eval/questions/olist_dev.yaml)",
    )
    leakage_parser.add_argument(
        "--threshold",
        type=float,
        default=0.80,
        help="Cosine/Jaccard similarity threshold for leakage violation (default: 0.80)",
    )
    leakage_parser.add_argument(
        "--json",
        dest="output_json",
        default=None,
        help="Optional path to write JSON leakage report",
    )

    # models
    models_parser = subparsers.add_parser("models", help="Model registry discovery, capabilities, and health probing")
    models_sub = models_parser.add_subparsers(dest="action")
    models_sub.add_parser("list", help="List all registered models and statuses")
    models_test_sub = models_sub.add_parser("test", help="Test a model with a tiny audited probe call")
    models_test_sub.add_argument("model_id", help="Model ID to probe (e.g. gemma4:e2b)")

    # verify-receipt
    receipt_parser = subparsers.add_parser("verify-receipt", help="Verify cryptographic SHA-256 hash chain and evidence integrity")
    receipt_parser.add_argument("receipt_file", help="Path to receipt.json")
    receipt_parser.add_argument("--replay", action="store_true", help="Re-execute SQL on database to detect data drift")

    args = parser.parse_args(argv)

    if not args.subcommand:
        parser.print_help()
        return 0

    if args.subcommand in ("ask", "run"):
        return handle_ask(args)

    if args.subcommand == "eval":
        return handle_eval(args)

    if args.subcommand == "check-leakage":
        return handle_check_leakage(args)

    if args.subcommand == "models":
        return handle_models(args)

    if args.subcommand == "verify-receipt":
        return handle_verify_receipt(args)

    if args.subcommand == "usage":
        return handle_usage(args)

    if args.subcommand == "warehouse-suspend":
        return handle_warehouse_suspend(args)

    if args.subcommand == "index":
        return handle_index(args)

    if args.subcommand == "serve":
        return handle_serve(args)

    if args.subcommand == "init":
        return handle_init(args)

    if args.subcommand == "demo":
        return handle_demo(args)

    if args.subcommand == "doctor":
        from datamind.doctor import print_doctor_report, run_diagnostics
        checks = run_diagnostics(config_path=getattr(args, "config", "datamind.yaml"))
        return print_doctor_report(checks)

    if args.subcommand == "mcp":
        from datamind.mcp_server import DataMindMCPServer
        server = DataMindMCPServer(config_path=getattr(args, "config", "datamind.yaml"))
        server.run_stdio()
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
