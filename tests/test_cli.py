"""Tests for datamind CLI entrypoint."""

import json
from unittest.mock import MagicMock, patch
import pytest

from datamind.agent.evidence import EvidenceStore
from datamind.agent.orchestrator import AgentResult
from datamind.agent.verifier import CitationReport, NumericCheck
from datamind.cli import main
from datamind.eval.runner import EvalItemResult, EvalReport


def test_cli_help(capsys: pytest.CaptureFixture):
    """Verify datamind --help returns exit code 0 and usage instructions."""
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "datamind" in captured.out
    assert "ask" in captured.out
    assert "eval" in captured.out
    assert "index" in captured.out


def test_cli_init_command(capsys: pytest.CaptureFixture, tmp_path):
    """Verify datamind init introspects database and writes semantic_model.yaml."""
    out_file = tmp_path / "model.yaml"
    exit_code = main(["init", "--db", "examples/primary/demo.duckdb", "--output", str(out_file)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Successfully introspected" in captured.out
    assert out_file.exists()


def test_cli_serve_command(capsys: pytest.CaptureFixture):
    """Verify datamind serve calls start_server with configured port."""
    with patch("datamind.server.start_server") as mock_start:
        exit_code = main(["serve", "--port", "8088"])
        assert exit_code == 0
        mock_start.assert_called_once_with(
            config_path="datamind.yaml",
            backend=None,
            host="127.0.0.1",
            port=8088,
            enable_uploads=False,
            keep_uploads=False,
        )


def test_cli_ask_empty_question(capsys: pytest.CaptureFixture):
    """datamind ask with no question returns exit code 1."""
    exit_code = main(["ask"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "No question provided" in captured.err


def test_cli_index_command(capsys: pytest.CaptureFixture):
    """datamind index builds the FTS index successfully."""
    exit_code = main(["index"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "FTS index built successfully" in captured.out


def test_cli_ask_with_mock_orchestrator(capsys: pytest.CaptureFixture):
    """datamind ask invokes orchestrator and prints answers and citations."""
    mock_evidence = EvidenceStore()
    mock_result = AgentResult(
        question="Which products declined most month over month?",
        answer="Novaship declined most in March 2026 [[Q1:R1]].",
        evidence_store=mock_evidence,
        citation_report=CitationReport(valid_count=1, invalid_count=0, is_clean=True),
        turns=2,
        success=True,
    )

    with patch("datamind.cli.AgentOrchestrator") as mock_orch_cls:
        mock_instance = MagicMock()
        mock_instance.run.return_value = mock_result
        mock_orch_cls.return_value = mock_instance

        exit_code = main(["ask", "Which products declined most month over month?"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "DATAMIND ANSWER" in captured.out
        assert "Novaship declined most" in captured.out


def test_cli_ask_json_output(capsys: pytest.CaptureFixture):
    """datamind ask --json outputs structured JSON."""
    mock_evidence = EvidenceStore()
    mock_result = AgentResult(
        question="Test Q",
        answer="Answer [[Q1:R1]]",
        evidence_store=mock_evidence,
        citation_report=CitationReport(valid_count=1, invalid_count=0, is_clean=True),
        turns=1,
        success=True,
    )

    with patch("datamind.cli.AgentOrchestrator") as mock_orch_cls:
        mock_instance = MagicMock()
        mock_instance.run.return_value = mock_result
        mock_orch_cls.return_value = mock_instance

        exit_code = main(["ask", "Test Q", "--json"])
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["question"] == "Test Q"
        assert data["citations"]["is_clean"] is True
        assert data["citations"]["valid_count"] == 1


def test_cli_ask_strict_fails_on_discrepancy():
    """datamind ask --strict fails when discrepancy is detected."""
    mock_evidence = EvidenceStore()
    mock_result = AgentResult(
        question="Test Q",
        answer="Discrepancy answer [[Q1:R1]]",
        evidence_store=mock_evidence,
        citation_report=CitationReport(
            valid_count=1,
            invalid_count=0,
            discrepancy_count=1,
            is_clean=False,
            numeric_checks=[
                NumericCheck(
                    raw_text="9999",
                    claimed_value=9999.0,
                    sentence="bad",
                    status="DISCREPANCY",
                    message="Number mismatch",
                )
            ],
        ),
        turns=1,
        success=True,
    )

    with patch("datamind.cli.AgentOrchestrator") as mock_orch_cls:
        mock_instance = MagicMock()
        mock_instance.run.return_value = mock_result
        mock_orch_cls.return_value = mock_instance

        # Strict by default: fails on discrepancy
        exit_code = main(["ask", "Test Q"])
        assert exit_code == 1

        # Permissive flag: passes
        exit_code_permissive = main(["ask", "Test Q", "--permissive"])
        assert exit_code_permissive == 0


def test_cli_eval_command(capsys: pytest.CaptureFixture):
    """datamind eval runs evaluation and prints summary."""
    mock_report = EvalReport(
        timestamp="2026-10-17T00:00:00",
        suite="trust",
        total=2,
        passed=2,
        failed=0,
        items=[
            EvalItemResult(
                item_id="T_TEST_1",
                suite="trust",
                question="Test question",
                passed=True,
                reason="Passed",
            )
        ],
    )

    with patch("datamind.cli.run_evaluation", return_value=mock_report):
        exit_code = main(["eval", "--suite", "trust"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "DATAMIND EVALUATION RUNNER" in captured.out
        assert "EVALUATION SUMMARY: 2 / 2 Passed" in captured.out


def test_cli_ask_reports_budget_exceeded_cleanly(capsys: pytest.CaptureFixture):
    """A budget stop must exit with a readable error, not a traceback."""
    from datamind.llm.budget import BudgetExceeded

    with patch("datamind.cli.AgentOrchestrator") as mock_orch_cls:
        mock_orch_cls.return_value.run.side_effect = BudgetExceeded("Token limit exceeded: test")
        exit_code = main(["ask", "How many products are there?"])

    assert exit_code == 2
    err = capsys.readouterr().err
    assert "budget guard" in err
    assert "Token limit exceeded: test" in err


def test_doctor_reads_ollama_context_from_modelfile_or_env():
    from datamind.doctor import ollama_configured_context

    assert ollama_configured_context("num_ctx                        16384\ntemperature 0") == 16384
    assert ollama_configured_context("temperature 0", env_value="8192") == 8192
    assert ollama_configured_context("temperature 0", env_value=None) is None
