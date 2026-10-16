"""Tests for datamind CLI entrypoint."""

import pytest
from datamind.cli import main


def test_cli_help(capsys: pytest.CaptureFixture):
    """Verify datamind --help returns exit code 0 and usage instructions."""
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "datamind" in captured.out
    assert "subcommands" in captured.out or "Available subcommands" in captured.out


def test_cli_subcommand_stubs(capsys: pytest.CaptureFixture):
    """Verify subcommand stubs print 'not implemented yet' and return 0."""
    for sub in ["init", "serve", "ask", "eval", "index"]:
        exit_code = main([sub])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert f"Command '{sub}' is not implemented yet" in captured.out
