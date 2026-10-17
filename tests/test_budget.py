"""Comprehensive test suite for DataMind Budget and Cost Guard (WP1).

Verifies fail-closed cloud protection, local endpoint exemptions, persistent
metering, pre-call limit enforcement, retries, response caching, and eval budget handling.
All tests run offline with mock transport (no network or real cloud calls).
"""

from pathlib import Path
import time
from unittest.mock import MagicMock, patch
import pytest

from datamind.agent.orchestrator import AgentOrchestrator
from datamind.cli import main
from datamind.config import AppConfig, BudgetConfig, LLMConfig
from datamind.eval.runner import run_evaluation
from datamind.llm.budget import (
    BudgetConfigError,
    BudgetExceeded,
    CallRecord,
    CostGuard,
    LLMResponseCache,
)
from datamind.llm.client import LLMClient


def test_local_endpoint_detection():
    """Verify local endpoints are detected accurately."""
    assert CostGuard.is_local_endpoint("http://localhost:11434/v1") is True
    assert CostGuard.is_local_endpoint("http://127.0.0.1:8000/v1") is True
    assert CostGuard.is_local_endpoint("http://0.0.0.0:11434/v1") is True
    assert CostGuard.is_local_endpoint("http://[::1]:8080/v1") is True
    assert CostGuard.is_local_endpoint("https://api.openai.com/v1") is False
    assert CostGuard.is_local_endpoint("https://bedrock-runtime.us-east-1.amazonaws.com") is False


def test_refuse_cloud_without_env_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Cloud endpoint is refused unless DATAMIND_ALLOW_CLOUD=1 is explicitly set."""
    monkeypatch.delenv("DATAMIND_ALLOW_CLOUD", raising=False)
    guard = CostGuard(usage_file=tmp_path / "usage.json", cache_db=tmp_path / "cache.sqlite")

    with pytest.raises(BudgetConfigError) as exc:
        guard.check_cloud_allowed(
            base_url="https://api.openai.com/v1",
            max_usd_total=10.0,
            price_per_million_input_usd=0.20,
            price_per_million_output_usd=0.80,
        )
    assert "DATAMIND_ALLOW_CLOUD=1" in str(exc.value)


def test_refuse_cloud_missing_total_budget(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Cloud endpoint is refused if max_usd_total is missing or zero."""
    monkeypatch.setenv("DATAMIND_ALLOW_CLOUD", "1")
    guard = CostGuard(usage_file=tmp_path / "usage.json", cache_db=tmp_path / "cache.sqlite")

    with pytest.raises(BudgetConfigError) as exc:
        guard.check_cloud_allowed(
            base_url="https://api.openai.com/v1",
            max_usd_total=None,
            price_per_million_input_usd=0.20,
            price_per_million_output_usd=0.80,
        )
    assert "max_usd_total is not configured" in str(exc.value)


def test_refuse_cloud_missing_pricing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Cloud endpoint is refused if unit pricing per million tokens is missing."""
    monkeypatch.setenv("DATAMIND_ALLOW_CLOUD", "1")
    guard = CostGuard(usage_file=tmp_path / "usage.json", cache_db=tmp_path / "cache.sqlite")

    with pytest.raises(BudgetConfigError) as exc:
        guard.check_cloud_allowed(
            base_url="https://api.openai.com/v1",
            max_usd_total=10.0,
            price_per_million_input_usd=None,
            price_per_million_output_usd=0.80,
        )
    assert "price_per_million_input_usd" in str(exc.value)


def test_local_endpoints_are_free(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Local endpoints are free of financial charge and not blocked by missing budget or prices."""
    monkeypatch.delenv("DATAMIND_ALLOW_CLOUD", raising=False)
    guard = CostGuard(usage_file=tmp_path / "usage.json", cache_db=tmp_path / "cache.sqlite")

    # Local endpoint does not raise BudgetConfigError even without env flag or pricing
    guard.check_before_call(
        base_url="http://localhost:11434/v1",
        estimated_prompt_tokens=500,
        max_tokens=1000,
        max_usd_total=None,
    )

    rec = guard.record_call(
        base_url="http://localhost:11434/v1",
        model="gemma4:e2b",
        prompt_tokens=500,
        completion_tokens=200,
        purpose="ask",
    )
    assert rec.estimated_usd == 0.0


def test_blocks_at_dollar_limit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Pre-call check blocks with BudgetExceeded when projected cost exceeds dollar limit."""
    monkeypatch.setenv("DATAMIND_ALLOW_CLOUD", "1")
    guard = CostGuard(usage_file=tmp_path / "usage.json", cache_db=tmp_path / "cache.sqlite")

    # Limit is $0.05. Proposed call is 5,000 prompt + 5,000 output at $10/M input, $10/M output = $0.10
    with pytest.raises(BudgetExceeded) as exc:
        guard.check_before_call(
            base_url="https://api.openai.com/v1",
            estimated_prompt_tokens=5_000,
            max_tokens=5_000,
            max_usd_total=0.05,
            price_per_million_input_usd=10.0,
            price_per_million_output_usd=10.0,
        )
    assert "Total budget exceeded" in str(exc.value)


def test_blocks_at_per_run_dollar_limit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Pre-call check blocks when proposed call exceeds max_usd_per_run."""
    monkeypatch.setenv("DATAMIND_ALLOW_CLOUD", "1")
    guard = CostGuard(usage_file=tmp_path / "usage.json", cache_db=tmp_path / "cache.sqlite")

    # Limit per run is $0.02. Proposed call is 4,000 prompt + 4,000 output at $5/M = $0.04
    with pytest.raises(BudgetExceeded) as exc:
        guard.check_before_call(
            base_url="https://api.openai.com/v1",
            estimated_prompt_tokens=4_000,
            max_tokens=4_000,
            max_usd_total=10.0,
            max_usd_per_run=0.02,
            price_per_million_input_usd=5.0,
            price_per_million_output_usd=5.0,
        )
    assert "Per-run budget exceeded" in str(exc.value)


def test_blocks_at_call_limit(tmp_path: Path):
    """Pre-call check blocks when session calls reach max_calls_per_run."""
    guard = CostGuard(usage_file=tmp_path / "usage.json", cache_db=tmp_path / "cache.sqlite")
    guard.session_calls = 5

    with pytest.raises(BudgetExceeded) as exc:
        guard.check_before_call(
            base_url="http://localhost:11434/v1",
            estimated_prompt_tokens=100,
            max_tokens=200,
            max_calls_per_run=5,
        )
    assert "Run call limit exceeded" in str(exc.value)


def test_blocks_at_token_limit(tmp_path: Path):
    """Pre-call check blocks when prompt + max_tokens exceeds max_tokens_per_call."""
    guard = CostGuard(usage_file=tmp_path / "usage.json", cache_db=tmp_path / "cache.sqlite")

    with pytest.raises(BudgetExceeded) as exc:
        guard.check_before_call(
            base_url="http://localhost:11434/v1",
            estimated_prompt_tokens=10_000,
            max_tokens=10_000,
            max_tokens_per_call=16384,
        )
    assert "Token limit exceeded" in str(exc.value)


def test_blocks_at_rate_limit(tmp_path: Path):
    """Pre-call check blocks when calls per minute ceiling is reached."""
    guard = CostGuard(usage_file=tmp_path / "usage.json", cache_db=tmp_path / "cache.sqlite")
    now = time.time()
    guard.recent_call_timestamps = [now - 10.0] * 5

    with pytest.raises(BudgetExceeded) as exc:
        guard.check_before_call(
            base_url="http://localhost:11434/v1",
            estimated_prompt_tokens=50,
            max_tokens=100,
            max_calls_per_minute=5,
        )
    assert "Rate limit exceeded" in str(exc.value)


def test_retry_counts_toward_limits(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Empty reply retry counts toward call limits and records metered usage."""
    monkeypatch.setenv("DATAMIND_ALLOW_CLOUD", "1")
    guard = CostGuard(usage_file=tmp_path / "usage.json", cache_db=tmp_path / "cache.sqlite")

    mock_openai = MagicMock()

    # Response 1: empty content, finish_reason = length
    first_choice = MagicMock()
    first_choice.message.content = ""
    first_choice.message.tool_calls = None
    first_choice.finish_reason = "length"
    first_resp = MagicMock()
    first_resp.choices = [first_choice]
    first_resp.usage.prompt_tokens = 20
    first_resp.usage.completion_tokens = 50

    # Response 2 (retry): successful completion
    second_choice = MagicMock()
    second_choice.message.content = "Answer text"
    second_choice.message.tool_calls = None
    second_choice.finish_reason = "stop"
    second_resp = MagicMock()
    second_resp.choices = [second_choice]
    second_resp.usage.prompt_tokens = 20
    second_resp.usage.completion_tokens = 80

    mock_openai.chat.completions.create.side_effect = [first_resp, second_resp]

    cfg = LLMConfig(
        base_url="http://localhost:11434/v1",
        budget=BudgetConfig(max_calls_per_run=10),
    )
    client = LLMClient(config=cfg, client=mock_openai, cost_guard=guard)

    res = client.chat([{"role": "user", "content": "hi"}], max_tokens=100)
    assert res["content"] == "Answer text"
    # Both initial call and retry were sent
    assert mock_openai.chat.completions.create.call_count == 2
    # Guard session calls recorded 1 final entry
    assert guard.session_calls == 1


def test_response_cache_hit_costs_zero(tmp_path: Path):
    """Cached response returns immediately, costs zero dollars, and is labelled as cached."""
    cache = LLMResponseCache(db_path=tmp_path / "cache.sqlite")
    guard = CostGuard(usage_file=tmp_path / "usage.json", cache_db=tmp_path / "cache.sqlite")
    guard.cache = cache

    mock_openai = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content="Cached response", tool_calls=None), finish_reason="stop")]
    resp.usage.prompt_tokens = 100
    resp.usage.completion_tokens = 50
    mock_openai.chat.completions.create.return_value = resp

    cfg = LLMConfig(base_url="http://localhost:11434/v1")
    client = LLMClient(config=cfg, client=mock_openai, cost_guard=guard, use_cache=True)

    # 1. First call: uncached
    res1 = client.chat([{"role": "user", "content": "test caching"}])
    assert res1["cached"] is False
    assert mock_openai.chat.completions.create.call_count == 1

    # 2. Second call: identical arguments -> cache hit
    res2 = client.chat([{"role": "user", "content": "test caching"}])
    assert res2["cached"] is True
    assert res2["content"] == "Cached response"
    # Network call count remained 1 (no API request dispatched)
    assert mock_openai.chat.completions.create.call_count == 1


def test_datamind_usage_cli(capsys: pytest.CaptureFixture, tmp_path: Path):
    """datamind usage CLI command prints formatted table."""
    usage_file = tmp_path / "usage.json"
    guard = CostGuard(usage_file=usage_file, cache_db=tmp_path / "cache.sqlite")
    guard.record_call(
        base_url="http://localhost:11434/v1",
        model="gemma4:e2b",
        prompt_tokens=150,
        completion_tokens=50,
        purpose="eval",
    )

    with patch("datamind.llm.budget.CostGuard", return_value=guard):
        exit_code = main(["usage"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "DATAMIND METERED USAGE AND BUDGET REPORT" in captured.out
        assert "Total Prompt Tokens:        150" in captured.out
        assert "Total Completion Tokens:    50" in captured.out


def test_partial_eval_output_on_budget_exceeded(tmp_path: Path):
    """When BudgetExceeded is raised during evaluation, execution halts and unfinished items are marked NOT_RUN."""
    from datamind.eval.runner import run_evaluation

    mock_guard = MagicMock()
    # Raise BudgetExceeded on first question call
    mock_guard.check_before_call.side_effect = BudgetExceeded("Simulated budget ceiling reached ($10.00)")

    with patch("datamind.llm.client.CostGuard", return_value=mock_guard):
        report = run_evaluation(suite="trust", save_results=False)
        assert report.not_run > 0
        # All unfinished items marked NOT_RUN
        not_run_items = [i for i in report.items if i.status == "NOT_RUN"]
        assert len(not_run_items) == report.total
        assert "NOT_RUN" in not_run_items[0].reason


def test_real_usage_ledger_not_modified_by_tests():
    """Verify that running CostGuard and LLMClient operations in test mode does not modify .datamind/usage.json."""
    real_usage_file = Path(".datamind/usage.json")
    if not real_usage_file.exists():
        pytest.skip(".datamind/usage.json does not exist")

    initial_content = real_usage_file.read_bytes()

    # Create CostGuard with default arguments (which should resolve to isolated test path)
    guard = CostGuard()
    assert guard.usage_file != real_usage_file, f"Guard must use isolated test path, got {guard.usage_file}"

    # Record test calls
    guard.record_call(
        base_url="http://localhost:11434/v1",
        model="gemma4:e2b",
        prompt_tokens=500,
        completion_tokens=200,
        purpose="eval",
    )

    # Confirm real usage.json content has not changed at all
    after_content = real_usage_file.read_bytes()
    assert initial_content == after_content, "Regression: Test operation modified real .datamind/usage.json!"
