"""Unit tests for append-only run ledger."""

from pathlib import Path
import pytest

from datamind.eval.ledger import LedgerEntry, RunLedger


def test_run_ledger_record_and_read(tmp_path: Path):
    ledger_file = tmp_path / "test_runs.jsonl"
    ledger = RunLedger(ledger_path=ledger_file)

    entry = LedgerEntry(
        run_id="run_test_001",
        timestamp="2026-10-17T20:00:00Z",
        git_commit="c8cbd68",
        suite_name="olist_dev",
        question_set_hash="test_q_hash",
        config_hash="test_cfg_hash",
        flags={"structured_query_lane": True},
        model="gemma4:e2b",
        backend="duckdb",
        total=30,
        passed=28,
        failed=2,
        not_run=0,
        pass_rate_pct=93.3,
        silent_wrong_count=0,
    )
    ledger.record_run(entry)

    runs = ledger.get_runs("olist_dev")
    assert len(runs) == 1
    assert runs[0]["run_id"] == "run_test_001"
    assert runs[0]["passed"] == 28

    # Generate markdown
    md = ledger.generate_ablation_markdown("olist_dev")
    assert "run_test_001" in md
    assert "93.3%" in md
