"""Provider settings tests for Google AI Studio and locally installed Ollama models."""

import json
import threading
import time
from http.client import HTTPConnection

import pytest

from datamind.config import load_config
from datamind.llm import google_ai, local_models
from datamind.server import server as server_mod
from datamind.server.server import create_server
from datamind.server.settings import SettingsStore

GOOGLE_MODELS = [
    {
        "id": "gemini-2.5-flash",
        "name": "Gemini 2.5 Flash",
        "description": "",
        "context_length": 1_048_576,
        "max_completion_tokens": 65_536,
        "supports_tools": True,
    },
]
LOCAL_MODELS = [
    {
        "id": "gemma3:12b",
        "name": "gemma3:12b",
        "size": 8_000_000_000,
        "family": "gemma3",
        "parameter_size": "12.2B",
        "quantization_level": "Q4_K_M",
        "modified_at": "2026-10-18T00:00:00Z",
    },
]


def test_bedrock_settings_discovery_selection_and_test_use_saved_credentials(provider_api, monkeypatch):
    from types import SimpleNamespace

    from datamind.llm import bedrock

    request, _, _ = provider_api
    catalogue_calls = []

    def models(key, bearer, endpoint):
        catalogue_calls.append((key, bearer, endpoint))
        return [{"id": "google.gemma-4-26b-a4b", "name": "Gemma"}]

    monkeypatch.setattr(bedrock, "list_models", models)
    endpoint = "https://bedrock-mantle.us-west-2.api.aws/v1"
    status, catalogue = request("POST", "/api/bedrock/models", {"bedrock_api_key": "test-bedrock-key", "bedrock_bearer_token": "test-bearer", "bedrock_base_url": endpoint})
    assert status == 200 and catalogue["models"][0]["id"].startswith("google.gemma")
    status, settings = request("POST", "/api/settings", {
        "provider": "bedrock", "bedrock_api_key": "test-bedrock-key", "bedrock_bearer_token": "test-bearer",
        "bedrock_model": "google.gemma-4-26b-a4b", "bedrock_base_url": endpoint,
    })
    assert status == 200 and settings["bedrock"]["active"]
    assert "test-bedrock-key" not in json.dumps(settings)
    assert catalogue_calls[-1] == ("test-bedrock-key", "test-bearer", endpoint)
    used = []

    def build(*args):
        used.append(args)
        return SimpleNamespace(chat=lambda *args, **kwargs: {"content": "Ready"})

    monkeypatch.setattr(bedrock, "build_client", build)
    assert request("POST", "/api/settings/test", {})[0] == 200
    assert used[0][:4] == ("test-bedrock-key", "test-bearer", "google.gemma-4-26b-a4b", endpoint)
    assert request("GET", "/api/config")[1]["model_name"] == "google.gemma-4-26b-a4b"


@pytest.fixture
def provider_api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAMIND_SETTINGS_PATH", str(tmp_path / "settings.json"))
    for name in ("OPENROUTER_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    google_calls: list[tuple[str, bool]] = []

    def fake_google_models(key: str, *, force: bool = False):
        google_calls.append((key, force))
        if key != "google-valid-secret-1234":
            raise google_ai.GoogleAIError("Google AI Studio rejected this Gemini API key.", 401)
        return GOOGLE_MODELS

    monkeypatch.setattr(google_ai, "list_models", fake_google_models)
    monkeypatch.setattr(local_models, "list_models", lambda _base_url: LOCAL_MODELS)

    config = load_config("datamind.yaml")
    server, adapter, retriever, upload_mgr = create_server(
        config, backend="duckdb", host="127.0.0.1", port=0
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.1)
    port = server.server_address[1]

    def request(method, path, body=None):
        connection = HTTPConnection("127.0.0.1", port)
        data = json.dumps(body).encode() if body is not None else None
        connection.request(method, path, body=data, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        payload = json.loads(response.read() or b"{}")
        connection.close()
        return response.status, payload

    yield request, server, google_calls
    server.shutdown()
    server.server_close()
    adapter.close()
    retriever.close()
    upload_mgr.cleanup_all()


def test_google_catalogue_keeps_only_chat_capable_gemini_models():
    payload = {"models": [
        {
            "name": "models/gemini-2.5-flash",
            "baseModelId": "gemini-2.5-flash",
            "displayName": "Gemini 2.5 Flash",
            "supportedGenerationMethods": ["generateContent", "countTokens"],
            "inputTokenLimit": 1_048_576,
            "outputTokenLimit": 65_536,
        },
        {
            "name": "models/gemini-embedding-001",
            "supportedGenerationMethods": ["embedContent"],
        },
        {
            "name": "models/gemini-2.5-flash-image",
            "supportedGenerationMethods": ["generateContent"],
        },
    ]}
    assert google_ai.parse_models(payload) == GOOGLE_MODELS


def test_ollama_catalogue_parses_installed_model_details():
    models = local_models.parse_models({"models": [{
        "name": "gemma3:12b",
        "model": "gemma3:12b",
        "size": 8_000_000_000,
        "modified_at": "2026-10-18T00:00:00Z",
        "details": {"family": "gemma3", "parameter_size": "12.2B", "quantization_level": "Q4_K_M"},
    }]})
    assert models == LOCAL_MODELS
    assert local_models.ollama_tags_url("http://localhost:11434/v1") == "http://localhost:11434/api/tags"
    with pytest.raises(local_models.LocalModelError):
        local_models.ollama_tags_url("https://example.com/v1")


def test_settings_store_persists_both_new_provider_choices_without_exposing_keys(tmp_path):
    store = SettingsStore(tmp_path / "settings.json", default_local_model="default:latest")
    store.update(
        provider="google",
        local_model="gemma3:12b",
        google_model="gemini-2.5-flash",
        google_api_key="google-valid-secret-1234",
    )
    public = store.public()
    assert public["local"]["model"] == "gemma3:12b"
    assert public["google"]["active"] is True
    assert public["google"]["key_hint"] == "…1234"
    assert "google-valid-secret" not in json.dumps(public)


def test_local_models_are_discovered_and_can_be_selected(provider_api):
    request, *_ = provider_api
    status, catalogue = request("GET", "/api/local/models")
    assert status == 200 and catalogue["models"] == LOCAL_MODELS
    status, settings = request("POST", "/api/settings", {
        "provider": "local", "local_model": "gemma3:12b",
    })
    assert status == 200
    assert settings["local"] == {"model": "gemma3:12b", "active": True}


def test_gemini_key_alone_loads_models_and_selects_first_available(provider_api):
    request, _, calls = provider_api
    status, catalogue = request("POST", "/api/google/models", {
        "google_api_key": "google-valid-secret-1234",
    })
    assert status == 200 and catalogue["models"] == GOOGLE_MODELS

    status, settings = request("POST", "/api/settings", {
        "provider": "google", "google_api_key": "google-valid-secret-1234",
    })
    assert status == 200
    assert settings["google"]["model"] == "gemini-2.5-flash"
    assert settings["google"]["active"] is True
    assert "google-valid-secret" not in json.dumps(settings)
    assert ("google-valid-secret-1234", True) in calls


def test_selected_gemini_model_is_used_for_questions(provider_api, monkeypatch):
    request, server, _ = provider_api
    request("POST", "/api/settings", {
        "provider": "google",
        "google_api_key": "google-valid-secret-1234",
        "google_model": "gemini-2.5-flash",
    })
    seen = []

    def fake_run(self, question, max_turns=6):
        seen.append((self.llm_client.config.base_url, self.llm_client.config.orchestrator_model))
        return object()

    monkeypatch.setattr(type(server.RequestHandlerClass.orchestrator), "run", fake_run)
    monkeypatch.setattr(server_mod, "format_orchestrator_result", lambda **kwargs: {"ok": True})
    status, body = request("POST", "/api/ask", {"question": "hello"})
    assert status == 200 and body == {"ok": True}
    assert seen == [(google_ai.GOOGLE_OPENAI_BASE_URL, "gemini-2.5-flash")]
