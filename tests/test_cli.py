"""Tests for datamind CLI entrypoint."""

import json
from unittest.mock import MagicMock, patch
import pytest

from datamind.agent.evidence import EvidenceStore
from datamind.agent.orchestrator import AgentResult
from datamind.agent.verifier import CitationReport
from datamind.cli import main


def test_cli_help(capsys: pytest.CaptureFixture):
    """Verify datamind --help returns exit code 0 and usage instructions."""
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "datamind" in captured.out
    assert "ask" in captured.out
    assert "index" in captured.out


def test_cli_subcommand_stubs(capsys: pytest.CaptureFixture):
    """Verify remaining subcommand stubs print 'not implemented yet' and return 0."""
    for sub in ["init", "serve", "eval"]:
        exit_code = main([sub])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert f"Command '{sub}' is not implemented yet" in captured.out


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
        assert "Citations: 1 valid, 0 invalid (PASS)" in captured.out


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
