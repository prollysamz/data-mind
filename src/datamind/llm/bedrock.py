"""Amazon Bedrock Mantle using its OpenAI-compatible API and bearer keys."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from openai import OpenAI, OpenAIError

from datamind.config import LLMConfig
from datamind.llm.budget import BudgetConfigError, CostGuard
from datamind.llm.client import LLMClient


class BedrockError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def base_url(region: str, route: str = "/openai/v1") -> str:
    if not re.fullmatch(r"[a-z]{2}(?:-gov)?-[a-z]+-\d", region) or route not in ("/v1", "/openai/v1"):
        raise BedrockError("Choose a valid AWS region and a /v1 or /openai/v1 route.", 400)
    return f"https://bedrock-mantle.{region}.api.aws{route}"


def validate_base_url(value: str) -> str:
    """Accept only an AWS Bedrock OpenAI-compatible endpoint.

    The settings form deliberately does not allow an arbitrary URL: credentials
    entered for Bedrock must never be sent to a user-controlled host.
    """
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").lower()
    valid_host = bool(re.fullmatch(r"bedrock-(?:mantle\.[a-z]{2}(?:-gov)?-[a-z]+-\d\.api\.aws|runtime\.[a-z]{2}(?:-gov)?-[a-z]+-\d\.amazonaws\.com)", host))
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment or not valid_host:
        raise BedrockError("Use an HTTPS Amazon Bedrock Mantle or Runtime base URL.", 400)
    path = parsed.path.rstrip("/")
    if path not in ("/v1", "/openai/v1"):
        raise BedrockError("The Bedrock base URL must end in /v1 or /openai/v1.", 400)
    return f"https://{host}{path}"


def _client(api_key: str, bearer_token: str, endpoint: str) -> OpenAI:
    # Bedrock accepts a bearer credential.  Supplying x-api-key as well supports
    # integrations that require the explicitly configured API key header.
    return OpenAI(
        api_key=bearer_token,
        base_url=endpoint,
        default_headers={"x-api-key": api_key},
        timeout=15,
        max_retries=0,
    )


def list_models(api_key: str, bearer_token: str, endpoint: str) -> list[dict]:
    if not api_key or not bearer_token:
        raise BedrockError("Enter both the Bedrock API key and AWS bearer token first.", 400)
    try:
        with _client(api_key, bearer_token, validate_base_url(endpoint)) as client:
            models = [{"id": m.id, "name": m.id} for m in client.models.list() if "gemma" in m.id.lower()]
    except OpenAIError as exc:
        status = getattr(exc, "status_code", 502)
        raise BedrockError("Could not list Gemma models from Bedrock Mantle. Check key, region, route and model access.", status) from exc
    if not models:
        raise BedrockError("No Gemma models were listed for this key and region. Check AWS model access and route.", 400)
    return sorted(models, key=lambda m: m["id"])


def build_client(api_key: str, bearer_token: str, model: str, endpoint: str, template: LLMConfig) -> LLMClient:
    if not api_key or not bearer_token or not model or "gemma" not in model.lower():
        raise BedrockError("Bedrock requires an API key, AWS bearer token, base URL, and a Gemma model for PS1.", 400)
    endpoint = validate_base_url(endpoint)
    budget = template.budget
    if (budget.max_usd_total is not None or budget.max_usd_per_run is not None) and (
        budget.price_per_million_input_usd is None or budget.price_per_million_output_usd is None
    ):
        raise BudgetConfigError("Set DATAMIND_PRICE_INPUT_M and DATAMIND_PRICE_OUTPUT_M for Bedrock before using a USD cap.")

    class OptedInGuard(CostGuard):
        def check_cloud_allowed(self, base_url: str, **kwargs) -> None:
            if base_url != endpoint:
                return super().check_cloud_allowed(base_url, **kwargs)
            # Selecting this cloud provider is consent, but never bypass a configured
            # financial ceiling when its price inputs are missing.
            if kwargs.get("max_usd_total") and (
                kwargs.get("price_per_million_input_usd") is None
                or kwargs.get("price_per_million_output_usd") is None
            ):
                raise BudgetConfigError("Set DATAMIND_PRICE_INPUT_M and DATAMIND_PRICE_OUTPUT_M for Bedrock before using a USD cap.")

    config = template.model_copy(update={
        "base_url": endpoint, "api_key": bearer_token, "orchestrator_model": model,
        "fast_model": model, "reasoning_model": model,
    })
    return LLMClient(
        config,
        client=_client(api_key, bearer_token, endpoint),
        cost_guard=OptedInGuard(),
        purpose="ask",
    )
