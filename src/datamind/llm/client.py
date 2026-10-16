"""OpenAI-compatible LLM client with retry, tool-calling round-trip, and token param handling."""

from __future__ import annotations

import logging
from typing import Any, Sequence
from openai import OpenAI
from datamind.config import LLMConfig

logger = logging.getLogger(__name__)


def build_tool_messages(assistant_message: dict[str, Any], tool_results: dict[str, str]) -> list[dict[str, Any]]:
    """Build tool response messages ensuring EVERY tool_call_id is answered.

    Args:
        assistant_message: The assistant message dict containing 'tool_calls'.
        tool_results: Mapping of tool_call_id -> result string.
                      If an ID is missing, a default empty/acknowledgement result is provided
                      so strict endpoints do not fail.
    Returns:
        List of role: 'tool' message dicts.
    """
    tool_calls = assistant_message.get("tool_calls") or []
    messages: list[dict[str, Any]] = []

    for call in tool_calls:
        # Handle call whether it is a dict or an object with an id attribute
        call_id = call["id"] if isinstance(call, dict) else getattr(call, "id", None)
        if not call_id:
            continue
        content = tool_results.get(call_id, '{"status": "acknowledged"}')
        messages.append({
            "role": "tool",
            "tool_call_id": call_id,
            "content": content,
        })

    return messages


class LLMClient:
    """Unified client for OpenAI-compatible endpoints (Bedrock Mantle, Ollama, vLLM)."""

    def __init__(
        self,
        config: LLMConfig | None = None,
        *,
        client: OpenAI | None = None,
    ) -> None:
        self.config = config or LLMConfig()
        if client is not None:
            self._client = client
        else:
            api_key = self.config.get_api_key() or "dummy-key-for-local"
            self._client = OpenAI(
                base_url=self.config.base_url,
                api_key=api_key,
                timeout=self.config.timeout_seconds,
            )

    def chat(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: str | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Send chat completion request to the OpenAI-compatible endpoint.

        Returns a standardized dict containing:
        - 'role': str ('assistant')
        - 'content': str | None
        - 'tool_calls': list | None
        - 'finish_reason': str | None
        - 'usage': dict
        - 'raw': raw message object
        """
        target_model = model or self.config.orchestrator_model
        token_limit = max_tokens or self.config.max_tokens
        temp = temperature if temperature is not None else self.config.temperature

        def _make_call(current_tokens: int) -> Any:
            kwargs: dict[str, Any] = {
                "model": target_model,
                "messages": list(messages),
                "temperature": temp,
            }
            if self.config.token_param == "max_completion_tokens":
                kwargs["max_completion_tokens"] = current_tokens
            else:
                kwargs["max_tokens"] = current_tokens

            if tools is not None:
                kwargs["tools"] = tools
            if response_format is not None:
                kwargs["response_format"] = response_format

            return self._client.chat.completions.create(**kwargs)

        response = _make_call(token_limit)
        choice = response.choices[0]
        message = choice.message
        finish_reason = getattr(choice, "finish_reason", None)

        # Truncation / empty reply detection for reasoning models:
        # If output content is empty, no tool calls, and finish_reason is 'length', retry once with double tokens.
        has_content = bool(message.content and message.content.strip())
        has_tools = bool(getattr(message, "tool_calls", None))

        if not has_content and not has_tools and finish_reason == "length":
            logger.warning(
                "Empty reply with finish_reason='length' for model %s. Retrying once with higher token limit (%d -> %d).",
                target_model,
                token_limit,
                token_limit * 2,
            )
            response = _make_call(token_limit * 2)
            choice = response.choices[0]
            message = choice.message
            finish_reason = getattr(choice, "finish_reason", None)

        tool_calls_list = None
        if hasattr(message, "tool_calls") and message.tool_calls:
            tool_calls_list = []
            for tc in message.tool_calls:
                tool_calls_list.append({
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                })

        usage_dict = {}
        if hasattr(response, "usage") and response.usage:
            usage_dict = {
                "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                "completion_tokens": getattr(response.usage, "completion_tokens", 0),
                "total_tokens": getattr(response.usage, "total_tokens", 0),
            }

        return {
            "role": "assistant",
            "content": message.content,
            "tool_calls": tool_calls_list,
            "finish_reason": finish_reason,
            "usage": usage_dict,
            "raw": message,
        }
