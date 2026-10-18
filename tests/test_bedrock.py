import json
from unittest.mock import patch

import pytest

from datamind.config import BudgetConfig, LLMConfig
from datamind.llm.bedrock import BedrockError, base_url, build_client, list_models, validate_base_url
from datamind.llm.budget import BudgetConfigError
from datamind.server.settings import SettingsStore


def test_bedrock_keys_persist_write_only_and_support_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-environment-bearer-value")
    monkeypatch.setenv("BEDROCK_API_KEY", "test-environment-api-key")
    path = tmp_path / "settings.json"
    settings = SettingsStore(path)
    assert settings.bedrock_bearer_token == "test-environment-bearer-value"
    assert settings.bedrock_api_key == "test-environment-api-key"
    settings.update(provider="bedrock", bedrock_api_key="test-private-key-1234", bedrock_bearer_token="test-bearer-1234", bedrock_base_url="https://bedrock-mantle.us-west-2.api.aws/v1", bedrock_model="google.gemma-4-26b-a4b")
    public = json.dumps(SettingsStore(path).public())
    assert "test-private-key-1234" not in public
    assert SettingsStore(path).public()["bedrock"]["active"]
    assert SettingsStore(path).bedrock_base_url.endswith("us-west-2.api.aws/v1")


def test_endpoint_is_restricted_to_aws_regions_and_documented_routes():
    assert base_url("us-east-1", "/v1") == "https://bedrock-mantle.us-east-1.api.aws/v1"
    for region, route in (("attacker.example", "/v1"), ("us-east-1", "/redirect")):
        with pytest.raises(BedrockError):
            base_url(region, route)
    assert validate_base_url("https://bedrock-mantle.us-east-1.api.aws/v1") == "https://bedrock-mantle.us-east-1.api.aws/v1"
    with pytest.raises(BedrockError):
        validate_base_url("https://attacker.example/v1")


def test_catalogue_is_fetched_with_key_and_filters_for_gemma():
    from types import SimpleNamespace

    with patch("datamind.llm.bedrock.OpenAI") as client:
        client.return_value.__enter__.return_value.models.list.return_value = [SimpleNamespace(id="google.gemma-4-26b-a4b"), SimpleNamespace(id="other-model")]
        endpoint = "https://bedrock-mantle.us-east-1.api.aws/v1"
        assert list_models("test-key", "test-bearer", endpoint) == [{"id": "google.gemma-4-26b-a4b", "name": "google.gemma-4-26b-a4b"}]
        assert client.call_args.kwargs["api_key"] == "test-bearer"
        assert client.call_args.kwargs["default_headers"] == {"x-api-key": "test-key"}


def test_bedrock_preserves_budget_and_does_not_bypass_missing_price_inputs():
    template = LLMConfig(budget=BudgetConfig(max_usd_total=10))
    with pytest.raises(BudgetConfigError, match="PRICE"):
        build_client("test-key", "test-bearer", "google.gemma-4-26b-a4b", "https://bedrock-mantle.us-east-1.api.aws/openai/v1", template)
    template.budget.price_per_million_input_usd = 1
    template.budget.price_per_million_output_usd = 2
    client = build_client("test-key", "test-bearer", "google.gemma-4-26b-a4b", "https://bedrock-mantle.us-east-1.api.aws/openai/v1", template)
    assert client.config.budget == template.budget
    assert client._client.api_key == "test-bearer"
