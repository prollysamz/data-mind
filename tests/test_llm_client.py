"""Tests for LLMClient and tool round-trip message building (offline with mock transport)."""

from unittest.mock import MagicMock

from datamind.config import LLMConfig
from datamind.llm.client import LLMClient, build_tool_messages


def test_build_tool_messages_answers_every_tool_call_id():
    """Verify that when an assistant message contains multiple tool calls,

    a role: 'tool' message is appended for EVERY tool_call_id.
    """
    assistant_msg = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": "call_abc_1", "type": "function", "function": {"name": "run_sql", "arguments": "{}"}},
            {"id": "call_def_2", "type": "function", "function": {"name": "search_documents", "arguments": "{}"}},
            {"id": "call_ghi_3", "type": "function", "function": {"name": "run_sql", "arguments": "{}"}},
        ],
    }

    tool_results = {
        "call_abc_1": '{"rows": [[100]]}',
        # Note: call_def_2 is omitted from results dict to test fallback
        "call_ghi_3": '{"rows": [[200]]}',
    }

    tool_messages = build_tool_messages(assistant_msg, tool_results)

    assert len(tool_messages) == 3
    assert [m["tool_call_id"] for m in tool_messages] == ["call_abc_1", "call_def_2", "call_ghi_3"]
    assert all(m["role"] == "tool" for m in tool_messages)
    assert tool_messages[0]["content"] == '{"rows": [[100]]}'
    assert "acknowledged" in tool_messages[1]["content"]  # fallback for missing result
    assert tool_messages[2]["content"] == '{"rows": [[200]]}'


def test_llm_client_empty_reply_retry_mock():
    """Verify that empty reply with finish_reason='length' triggers retry with doubled max_tokens."""
    mock_openai = MagicMock()

    # First response: empty content, finish_reason = "length"
    first_choice = MagicMock()
    first_choice.message.content = ""
    first_choice.message.tool_calls = None
    first_choice.finish_reason = "length"
    first_resp = MagicMock()
    first_resp.choices = [first_choice]
    first_resp.usage.prompt_tokens = 10
    first_resp.usage.completion_tokens = 50
    first_resp.usage.total_tokens = 60

    # Second response (retry): valid content
    second_choice = MagicMock()
    second_choice.message.content = "Here is the completed answer after retry."
    second_choice.message.tool_calls = None
    second_choice.finish_reason = "stop"
    second_resp = MagicMock()
    second_resp.choices = [second_choice]
    second_resp.usage.prompt_tokens = 10
    second_resp.usage.completion_tokens = 100
    second_resp.usage.total_tokens = 110

    mock_openai.chat.completions.create.side_effect = [first_resp, second_resp]

    cfg = LLMConfig(max_tokens=100)
    client = LLMClient(config=cfg, client=mock_openai)

    res = client.chat([{"role": "user", "content": "Tell me a story"}])

    assert res["content"] == "Here is the completed answer after retry."
    assert res["finish_reason"] == "stop"
    assert mock_openai.chat.completions.create.call_count == 2

    # Verify first call had max_tokens=100, second call had max_tokens=200
    first_call_kwargs = mock_openai.chat.completions.create.call_args_list[0].kwargs
    second_call_kwargs = mock_openai.chat.completions.create.call_args_list[1].kwargs
    assert first_call_kwargs["max_tokens"] == 100
    assert second_call_kwargs["max_tokens"] == 200


def test_llm_client_token_param_selection():
    """Verify token_param switches between max_tokens and max_completion_tokens."""
    mock_openai = MagicMock()

    resp = MagicMock()
    choice = MagicMock()
    choice.message.content = "OK"
    choice.message.tool_calls = None
    choice.finish_reason = "stop"
    resp.choices = [choice]
    resp.usage = None
    mock_openai.chat.completions.create.return_value = resp

    cfg = LLMConfig(token_param="max_completion_tokens", max_tokens=150)
    client = LLMClient(config=cfg, client=mock_openai)
    client.chat([{"role": "user", "content": "Hi"}])

    call_kwargs = mock_openai.chat.completions.create.call_args.kwargs
    assert "max_completion_tokens" in call_kwargs
    assert call_kwargs["max_completion_tokens"] == 150
    assert "max_tokens" not in call_kwargs


def _stop_resp(text: str = "OK") -> MagicMock:
    choice = MagicMock()
    choice.message.content = text
    choice.message.tool_calls = None
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = None
    return resp


def _empty_length_resp() -> MagicMock:
    resp = _stop_resp("")
    resp.choices[0].finish_reason = "length"
    return resp


def test_local_endpoint_disables_thinking_by_default():
    mock_openai = MagicMock()
    mock_openai.chat.completions.create.return_value = _stop_resp()

    client = LLMClient(config=LLMConfig(base_url="http://localhost:11434/v1"), client=mock_openai)
    client.chat([{"role": "user", "content": "Hi"}])

    kwargs = mock_openai.chat.completions.create.call_args.kwargs
    assert kwargs["extra_body"]["reasoning_effort"] == "none"


def test_thinking_true_does_not_send_reasoning_effort():
    mock_openai = MagicMock()
    mock_openai.chat.completions.create.return_value = _stop_resp()

    client = LLMClient(
        config=LLMConfig(base_url="http://localhost:11434/v1", thinking=True), client=mock_openai
    )
    client.chat([{"role": "user", "content": "Hi"}])

    assert "extra_body" not in mock_openai.chat.completions.create.call_args.kwargs


def test_reasoning_effort_rejection_falls_back_and_is_remembered():
    from openai import BadRequestError

    mock_openai = MagicMock()
    rejected = BadRequestError(
        "model does not support thinking", response=MagicMock(status_code=400), body=None
    )
    mock_openai.chat.completions.create.side_effect = [rejected, _stop_resp(), _stop_resp()]

    client = LLMClient(config=LLMConfig(base_url="http://localhost:11434/v1"), client=mock_openai)
    assert client.chat([{"role": "user", "content": "Hi"}])["content"] == "OK"
    client.chat([{"role": "user", "content": "Again"}])

    calls = mock_openai.chat.completions.create.call_args_list
    assert len(calls) == 3  # rejected attempt, fallback, then a single call once remembered
    assert "extra_body" not in calls[1].kwargs
    assert "extra_body" not in calls[2].kwargs


def test_length_retry_is_clamped_to_per_call_budget():
    from datamind.config import BudgetConfig

    mock_openai = MagicMock()
    mock_openai.chat.completions.create.side_effect = [_empty_length_resp(), _stop_resp("done")]

    cfg = LLMConfig(max_tokens=800, budget=BudgetConfig(max_tokens_per_call=1000))
    client = LLMClient(config=cfg, client=mock_openai)
    res = client.chat([{"role": "user", "content": "x" * 35}])  # ~10 prompt tokens

    assert res["content"] == "done"
    retry_kwargs = mock_openai.chat.completions.create.call_args_list[1].kwargs
    assert 800 < retry_kwargs["max_tokens"] <= 1000 - 10


def test_length_retry_skipped_without_budget_headroom():
    from datamind.config import BudgetConfig
    from datamind.llm.client import _estimate_tokens

    messages = [{"role": "user", "content": "x" * 350}]
    # The first call exactly fills the per-call cap, so a larger retry could never be allowed.
    cfg = LLMConfig(
        max_tokens=1000 - _estimate_tokens(messages),
        budget=BudgetConfig(max_tokens_per_call=1000),
    )
    mock_openai = MagicMock()
    mock_openai.chat.completions.create.return_value = _empty_length_resp()

    res = LLMClient(config=cfg, client=mock_openai).chat(messages)

    assert mock_openai.chat.completions.create.call_count == 1
    assert res["finish_reason"] == "length"
