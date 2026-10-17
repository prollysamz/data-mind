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


from datamind.llm.budget import CostGuard, LLMResponseCache, BudgetConfigError, BudgetExceeded


def _estimate_tokens(msgs: Sequence[dict[str, Any]]) -> int:
    """Conservatively estimate prompt tokens from character counts."""
    char_len = sum(
        len(str(m.get("content") or "")) + len(str(m.get("tool_calls") or "")) + len(str(m.get("role") or ""))
        for m in msgs
    )
    return max(int(char_len / 3.5), 10)


class LLMClient:
    """Unified client for OpenAI-compatible endpoints (Bedrock Mantle, Ollama, vLLM)."""

    def __init__(
        self,
        config: LLMConfig | None = None,
        *,
        client: OpenAI | None = None,
        cost_guard: CostGuard | None = None,
        use_cache: bool = False,
        purpose: str = "ask",
    ) -> None:
        self.config = config or LLMConfig()
        self.cost_guard = cost_guard or CostGuard()
        self.use_cache = use_cache
        self.purpose = purpose
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
        """Send chat completion request with budget guarding, metering, and caching."""
        target_model = model or self.config.orchestrator_model
        token_limit = max_tokens or self.config.max_tokens
        temp = temperature if temperature is not None else self.config.temperature

        # 1. Response Cache Check
        cache_key = None
        if self.use_cache:
            cache_key = LLMResponseCache.compute_key(
                model=target_model,
                messages=messages,
                tools=tools,
                temperature=temp,
                max_tokens=token_limit,
            )
            cached_val = self.cost_guard.cache.get(cache_key)
            if cached_val is not None:
                cached_copy = dict(cached_val)
                cached_copy["cached"] = True
                cached_usage = cached_copy.get("usage", {})
                self.cost_guard.record_call(
                    base_url=self.config.base_url,
                    model=target_model,
                    prompt_tokens=cached_usage.get("prompt_tokens", 0),
                    completion_tokens=cached_usage.get("completion_tokens", 0),
                    is_estimated=False,
                    purpose=self.purpose,
                    cached=True,
                )
                return cached_copy

        # 2. Pre-call Budget & Safety Enforcement
        prompt_tok_estimate = _estimate_tokens(messages)
        b = self.config.budget
        self.cost_guard.check_before_call(
            base_url=self.config.base_url,
            estimated_prompt_tokens=prompt_tok_estimate,
            max_tokens=token_limit,
            max_usd_total=b.max_usd_total,
            max_usd_per_run=b.max_usd_per_run,
            max_calls_per_run=b.max_calls_per_run,
            max_tokens_per_call=b.max_tokens_per_call,
            max_calls_per_minute=b.max_calls_per_minute,
            price_per_million_input_usd=b.price_per_million_input_usd,
            price_per_million_output_usd=b.price_per_million_output_usd,
        )

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

            # Enforce dynamic prediction limit in Ollama options
            kwargs["extra_body"] = {"options": {"num_ctx": 16384, "num_predict": current_tokens}}

            return self._client.chat.completions.create(**kwargs)

        response = _make_call(token_limit)
        choice = response.choices[0]
        message = choice.message
        finish_reason = getattr(choice, "finish_reason", None)

        # Retry logic: at most 1 retry per call, strictly budget-metered and pre-checked
        has_content = bool(message.content and message.content.strip())
        has_tools = bool(getattr(message, "tool_calls", None))

        if not has_content and not has_tools and finish_reason == "length":
            logger.warning(
                "Empty reply with finish_reason='length' for model %s. Retrying once with higher token limit (%d -> %d).",
                target_model,
                token_limit,
                token_limit * 2,
            )
            self.cost_guard.check_before_call(
                base_url=self.config.base_url,
                estimated_prompt_tokens=prompt_tok_estimate,
                max_tokens=token_limit * 2,
                max_usd_total=b.max_usd_total,
                max_usd_per_run=b.max_usd_per_run,
                max_calls_per_run=b.max_calls_per_run,
                max_tokens_per_call=b.max_tokens_per_call,
                max_calls_per_minute=b.max_calls_per_minute,
                price_per_million_input_usd=b.price_per_million_input_usd,
                price_per_million_output_usd=b.price_per_million_output_usd,
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
        p_tok = prompt_tok_estimate
        c_tok = max(len(str(message.content or "")) // 4, 1)
        is_est = True

        if hasattr(response, "usage") and response.usage:
            raw_p = getattr(response.usage, "prompt_tokens", None)
            raw_c = getattr(response.usage, "completion_tokens", None)
            if raw_p is not None and raw_c is not None:
                p_tok = int(raw_p)
                c_tok = int(raw_c)
                is_est = False
            usage_dict = {
                "prompt_tokens": p_tok,
                "completion_tokens": c_tok,
                "total_tokens": p_tok + c_tok,
            }
        else:
            usage_dict = {
                "prompt_tokens": p_tok,
                "completion_tokens": c_tok,
                "total_tokens": p_tok + c_tok,
            }

        # 3. Post-call Metering Record
        self.cost_guard.record_call(
            base_url=self.config.base_url,
            model=target_model,
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            is_estimated=is_est,
            price_per_million_input_usd=b.price_per_million_input_usd,
            price_per_million_output_usd=b.price_per_million_output_usd,
            purpose=self.purpose,
            cached=False,
        )

        result_dict = {
            "role": "assistant",
            "content": message.content,
            "tool_calls": tool_calls_list,
            "finish_reason": finish_reason,
            "usage": usage_dict,
            "raw": message,
            "cached": False,
        }

        # 4. Save to Response Cache
        if self.use_cache and cache_key:
            self.cost_guard.cache.set(cache_key, target_model, result_dict)

        return result_dict
