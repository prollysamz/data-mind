"""Tests for the OpenRouter provider settings, free-model catalogue and per-question routing."""

import json
import threading
import time
from http.client import HTTPConnection
from unittest.mock import MagicMock

import pytest

from datamind.config import load_config
from datamind.llm import openrouter
from datamind.server import server as server_mod
from datamind.server.server import create_server
from datamind.server.settings import SettingsStore

CATALOGUE = {
    "data": [
        {"id": "meta/free-tools:free", "name": "Free With Tools", "context_length": 32000,
         "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["tools", "temperature"],
         "architecture": {"output_modalities": ["text"]}},
        {"id": "acme/free-plain:free", "name": "Another Free", "context_length": 8000,
         "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["temperature"],
         "architecture": {"output_modalities": ["text"]}},
        {"id": "acme/paid", "name": "Paid", "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
        {"id": "acme/free-image", "name": "Image", "pricing": {"prompt": "0", "completion": "0"},
         "architecture": {"output_modalities": ["image"]}},
        {"id": "acme/no-pricing", "name": "Unknown price"},
    ]
}


@pytest.fixture(autouse=True)
def reset_catalogue_cache():
    openrouter._cache.update({"at": 0.0, "models": []})
    yield
    openrouter._cache.update({"at": 0.0, "models": []})


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAMIND_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    calls = []

    def fake_get_json(url, api_key=None):
        calls.append((url, api_key))
        if url == openrouter.MODELS_URL:
            return CATALOGUE
        if api_key == "sk-or-valid-key-1234":
            return {"data": {"label": "test"}}
        raise openrouter.OpenRouterError("OpenRouter rejected this API key.", status=401)

    monkeypatch.setattr(openrouter, "_get_json", fake_get_json)

    config = load_config("datamind.yaml")
    server, adapter, retriever, upload_mgr = create_server(config, backend="duckdb", host="127.0.0.1", port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.1)
    port = server.server_address[1]

    def request(method, path, body=None, headers=None):
        connection = HTTPConnection("127.0.0.1", port)
        data = json.dumps(body).encode() if body is not None else None
        all_headers = {"Content-Type": "application/json", **(headers or {})}
        connection.request(method, path, body=data, headers=all_headers)
        response = connection.getresponse()
        payload = json.loads(response.read() or b"{}")
        connection.close()
        return response.status, payload

    yield request, server, tmp_path, calls
    server.shutdown()
    server.server_close()
    adapter.close()
    retriever.close()
    upload_mgr.cleanup_all()


def test_parse_free_models_keeps_only_free_text_models_with_tool_support_first():
    models = openrouter.parse_free_models(CATALOGUE)
    assert [m["id"] for m in models] == ["meta/free-tools:free", "acme/free-plain:free"]
    assert models[0]["supports_tools"] is True and models[1]["supports_tools"] is False


def test_settings_store_persists_and_never_exposes_the_key(tmp_path):
    store = SettingsStore(tmp_path / "s.json")
    store.update(provider="openrouter", model="meta/free-tools:free", api_key="sk-or-secret-abcd")
    reloaded = SettingsStore(tmp_path / "s.json")
    assert reloaded.openrouter_active()
    public = json.dumps(reloaded.public())
    assert "sk-or-secret" not in public
    assert "abcd" in public
    reloaded.update(api_key="")
    assert not SettingsStore(tmp_path / "s.json").openrouter_active()


def test_models_endpoint_lists_free_models(api):
    request, *_ = api
    status, body = request("GET", "/api/openrouter/models")
    assert status == 200
    assert [m["id"] for m in body["models"]] == ["meta/free-tools:free", "acme/free-plain:free"]


def test_saving_a_key_validates_it_and_hides_it_in_responses(api):
    request, _, _, calls = api
    status, body = request("POST", "/api/settings", {
        "openrouter_api_key": "sk-or-valid-key-1234", "openrouter_model": "meta/free-tools:free", "provider": "openrouter",
    })
    assert status == 200
    assert body["provider"] == "openrouter" and body["openrouter"]["active"] is True
    assert "sk-or-valid" not in json.dumps(body)
    assert ("https://openrouter.ai/api/v1/auth/key", "sk-or-valid-key-1234") in calls
    status, body = request("GET", "/api/settings")
    assert body["openrouter"]["key_hint"] == "…1234"
    assert "sk-or-valid" not in json.dumps(body)


def test_invalid_key_is_rejected_and_not_saved(api):
    request, *_ = api
    status, _ = request("POST", "/api/settings", {"openrouter_api_key": "sk-or-wrong-key-0000"})
    assert status == 401
    assert request("GET", "/api/settings")[1]["openrouter"]["configured"] is False


def test_paid_or_unknown_models_cannot_be_selected(api):
    request, *_ = api
    request("POST", "/api/settings", {"openrouter_api_key": "sk-or-valid-key-1234"})
    for model in ("acme/paid", "does/not-exist"):
        status, body = request("POST", "/api/settings", {"openrouter_model": model})
        assert status == 400 and "free" in body["error"]


def test_cannot_switch_to_openrouter_without_key_and_model(api):
    request, *_ = api
    status, _ = request("POST", "/api/settings", {"provider": "openrouter"})
    assert status == 400


def test_cross_origin_settings_write_is_refused(api):
    request, *_ = api
    status, _ = request("POST", "/api/settings", {"provider": "local"}, headers={"Origin": "https://attacker.example"})
    assert status == 403


def test_ask_routes_through_openrouter_only_while_active(api, monkeypatch):
    request, server, *_ = api
    seen = []

    def fake_run(self, question, max_turns=6):
        seen.append((self.llm_client.config.base_url, self.llm_client.config.orchestrator_model))
        return object()

    monkeypatch.setattr(type(server.RequestHandlerClass.orchestrator), "run", fake_run)
    monkeypatch.setattr(server_mod, "format_orchestrator_result", lambda **kwargs: {"ok": True})

    request("POST", "/api/ask", {"question": "hello"})
    request("POST", "/api/settings", {
        "openrouter_api_key": "sk-or-valid-key-1234", "openrouter_model": "meta/free-tools:free", "provider": "openrouter",
    })
    request("POST", "/api/ask", {"question": "hello", "preset": "cloud_accuracy"})
    request("POST", "/api/settings", {"provider": "local"})
    request("POST", "/api/ask", {"question": "hello"})

    assert seen[0][0].startswith("http://localhost")
    assert seen[1] == ("https://openrouter.ai/api/v1", "meta/free-tools:free")
    assert seen[2][0].startswith("http://localhost")
    # the shared orchestrator is always handed back its local client
    assert server.RequestHandlerClass.orchestrator.llm_client.config.base_url.startswith("http://localhost")


def test_provider_auth_failures_become_actionable_messages(api, monkeypatch):
    from types import SimpleNamespace

    from openai import AuthenticationError, RateLimitError

    request, server, *_ = api
    request("POST", "/api/settings", {
        "openrouter_api_key": "sk-or-valid-key-1234", "openrouter_model": "meta/free-tools:free", "provider": "openrouter",
    })

    def fake_response(code):
        return SimpleNamespace(status_code=code, headers={}, request=None)

    errors = iter([AuthenticationError("bad", response=fake_response(401), body=None),
                   RateLimitError("slow", response=fake_response(429), body=None)])

    def failing_run(self, question, max_turns=6):
        raise next(errors)

    monkeypatch.setattr(type(server.RequestHandlerClass.orchestrator), "run", failing_run)
    status, body = request("POST", "/api/ask", {"question": "hello"})
    assert status == 401 and "Settings" in body["error"]
    status, body = request("POST", "/api/ask", {"question": "hello"})
    assert status == 429 and "rate limited" in body["error"]


def test_catalogue_includes_multimodal_text_but_excludes_request_fees_and_tiny_prices():
    def entry(model_id, **values):
        return {"id": model_id, "pricing": {"prompt": "0", "completion": "0"}, **values}

    models = openrouter.parse_free_models({"data": [
        entry("text-and-image", architecture={"input_modalities": ["text", "image"], "output_modalities": ["text", "image"]}),
        entry("request-fee", pricing={"prompt": "0", "completion": "0", "request": "0.1"}),
        entry("tiny-price", pricing={"prompt": "1e-999", "completion": "0"}),
        entry("audio-only-input", architecture={"input_modalities": ["audio"], "output_modalities": ["text"]}),
    ]})
    assert [model["id"] for model in models] == ["text-and-image"]


@pytest.mark.parametrize("payload", [None, [], {}, {"data": {}}])
def test_bad_catalogue_is_reported_without_crashing(payload):
    with pytest.raises(openrouter.OpenRouterError):
        openrouter.parse_free_models(payload)


def test_failed_disk_write_leaves_previous_settings_unchanged(tmp_path, monkeypatch):
    store = SettingsStore(tmp_path / "settings.json")
    store.update(provider="local")
    monkeypatch.setattr(store, "_write", MagicMock(side_effect=OSError("read only")))
    with pytest.raises(OSError):
        store.update(provider="openrouter", model="free", api_key="secret")
    assert store.provider == "local" and not store.api_key
    assert SettingsStore(store.path).provider == "local"


@pytest.mark.parametrize("body", [[], None, "string", 42])
def test_settings_rejects_non_object_json(api, body):
    request, *_ = api
    assert request("POST", "/api/settings", body)[0] == 400


def test_settings_rejects_simple_cross_site_form_content_type(api):
    request, *_ = api
    assert request("POST", "/api/settings", {"provider": "local"}, headers={"Content-Type": "text/plain"})[0] == 403


def test_switching_back_to_a_retired_free_model_is_rejected(api, monkeypatch):
    request, server, *_ = api
    server.RequestHandlerClass.settings.update(model="formerly/free")
    status, body = request("POST", "/api/settings", {"provider": "openrouter", "openrouter_api_key": "sk-or-valid-key-1234"})
    assert status == 400 and "free" in body["error"]


def test_retired_model_does_not_fall_back_to_local_during_ask(api, monkeypatch):
    request, server, *_ = api
    server.RequestHandlerClass.settings.update(provider="openrouter", model="formerly/free", api_key="test-key")
    run = MagicMock()
    monkeypatch.setattr(type(server.RequestHandlerClass.orchestrator), "run", run)
    status, body = request("POST", "/api/ask", {"question": "hello"})
    assert status == 400 and "no longer" in body["error"]
    run.assert_not_called()


def test_settings_write_failure_returns_an_error_and_retains_local_provider(api, monkeypatch):
    request, server, *_ = api
    monkeypatch.setattr(server.RequestHandlerClass.settings, "_write", MagicMock(side_effect=OSError("disk full")))
    status, body = request("POST", "/api/settings", {"provider": "local"})
    assert status == 500 and "unchanged" in body["error"]


def _response(content):
    from types import SimpleNamespace
    return SimpleNamespace(usage=None, choices=[SimpleNamespace(
        message=SimpleNamespace(content=content, tool_calls=None), finish_reason="stop",
    )])


def test_native_openrouter_call_has_free_price_ceiling_and_no_ollama_options(api):
    client = openrouter.build_client("test-key", "meta/free-tools:free")
    client._client = MagicMock()
    client._client.chat.completions.create.return_value = _response("OK")
    client.chat([{"role": "user", "content": "hello"}])
    call = client._client.chat.completions.create.call_args.kwargs
    assert call["extra_body"] == {"provider": {"max_price": {"prompt": 0, "completion": 0, "request": 0}}}
    assert call["model"] == "meta/free-tools:free"
    assert "options" not in call["extra_body"]


def test_text_only_model_round_trips_tools_and_final_answer(api):
    client = openrouter.build_client("test-key", "acme/free-plain:free")
    client._client = MagicMock()
    create = client._client.chat.completions.create
    create.side_effect = [
        _response('```json\n{"tool_calls":[{"name":"run_sql","arguments":{"sql":"SELECT 1"}}]}\n```'),
        _response('{"answer":"Result is 1 [[Q1:R1]]."}'),
    ]
    tools = [{"type": "function", "function": {"name": "run_sql", "parameters": {"type": "object"}}}]
    messages = [{"role": "user", "content": "Count"}]
    reply = client.chat(messages, tools=tools)
    assert reply["tool_calls"][0]["function"]["name"] == "run_sql"
    assert "tools" not in create.call_args.kwargs
    messages += [
        {"role": "assistant", "content": None, "tool_calls": reply["tool_calls"]},
        {"role": "tool", "tool_call_id": reply["tool_calls"][0]["id"], "content": "1 [[Q1:R1]]"},
    ]
    assert client.chat(messages, tools=tools)["content"] == "Result is 1 [[Q1:R1]]."
    assert all(message["role"] != "tool" and "tool_calls" not in message for message in create.call_args.kwargs["messages"])


@pytest.mark.parametrize("content", [
    '{"tool_calls":[{"name":"delete_database","arguments":{}}]}',
    '{"tool_calls":[{"name":"run_sql","arguments":"bad"}]}',
    '{"tool_calls":[]}',
])
def test_text_tool_compatibility_rejects_invalid_calls(api, content):
    client = openrouter.build_client("test-key", "acme/free-plain:free")
    client._client = MagicMock()
    client._client.chat.completions.create.return_value = _response(content)
    with pytest.raises(openrouter.OpenRouterError):
        client.chat([{"role": "user", "content": "Count"}], tools=[{"function": {"name": "run_sql"}}])


def test_upload_questions_use_selected_provider_and_close_resources_on_provider_failure(api, monkeypatch):
    from types import SimpleNamespace

    from openai import RateLimitError

    request, server, *_ = api
    request("POST", "/api/settings", {
        "provider": "openrouter", "openrouter_model": "meta/free-tools:free", "openrouter_api_key": "sk-or-valid-key-1234",
    })
    orchestrator, adapter, retriever = MagicMock(), MagicMock(), MagicMock()
    closed = threading.Event()
    retriever.close.side_effect = closed.set
    orchestrator.run.side_effect = RateLimitError("rate limited", response=SimpleNamespace(
        status_code=429, headers={}, request=None), body=None)
    monkeypatch.setattr(server.RequestHandlerClass.upload_manager, "create_session_orchestrator",
                        lambda **kwargs: (orchestrator, adapter, retriever))
    status, body = request("POST", "/api/uploads/test-session/ask", {"question": "hello"})
    assert status == 429 and "Settings" in body["error"]
    assert orchestrator.llm_client.config.orchestrator_model == "meta/free-tools:free"
    assert closed.wait(2), "Upload resources were not closed after the response"
    adapter.close.assert_called_once()
    retriever.close.assert_called_once()


def test_model_test_reports_empty_response_as_failure(api, monkeypatch):
    request, server, *_ = api
    request("POST", "/api/settings", {
        "provider": "openrouter", "openrouter_model": "meta/free-tools:free", "openrouter_api_key": "sk-or-valid-key-1234",
    })
    client = MagicMock()
    client.chat.return_value = {"content": ""}
    monkeypatch.setattr(server.RequestHandlerClass, "_openrouter_client", lambda self, **kwargs: client)
    status, body = request("POST", "/api/settings/test", {})
    assert status == 502 and "empty" in body["error"]


@pytest.mark.parametrize("model_id", ["meta/free-tools:free", "acme/free-plain:free"])
def test_real_agent_sql_and_evidence_round_trip_with_selected_free_model(api, monkeypatch, model_id):
    request, server, *_ = api
    server.RequestHandlerClass.orchestrator.config.answerability_check = False
    request("POST", "/api/settings", {
        "provider": "openrouter", "openrouter_model": model_id, "openrouter_api_key": "sk-or-valid-key-1234",
    })
    client = openrouter.build_client("test-key", model_id)
    client._client = MagicMock()
    tool_reply = _response(None)
    from types import SimpleNamespace
    tool_reply.choices[0].message.tool_calls = [SimpleNamespace(
        id="sql-call", type="function", function=SimpleNamespace(name="run_sql", arguments=json.dumps({
            "sql": "SELECT SUM(amount) AS total_revenue FROM SALES", "purpose": "Find total sales revenue",
        })),
    )]
    tool_reply.choices[0].finish_reason = "tool_calls"
    answer = "Total sales revenue is $1,300,674.43 [[Q1:R1]]."
    if model_id == "acme/free-plain:free":
        tool_reply = _response(json.dumps({"tool_calls": [{"name": "run_sql", "arguments": {
            "sql": "SELECT SUM(amount) AS total_revenue FROM SALES", "purpose": "Find total sales revenue",
        }}]}))
        final_reply = _response(json.dumps({"answer": answer}))
    else:
        final_reply = _response(answer)
    client._client.chat.completions.create.side_effect = [tool_reply, final_reply]
    monkeypatch.setattr(server.RequestHandlerClass, "_openrouter_client", lambda self, **kwargs: client)
    status, body = request("POST", "/api/ask", {"question": "What is the total sales revenue?", "model_id": "old-local-selection"})
    assert status == 200 and body["answer"] == answer
    assert float(body["evidence"]["queries"][0]["rows"][0][0]) == 1300674.43
    assert body["under_the_hood"]["model"] == model_id
    assert body["citation_report"]["is_clean"]
    assert body["egress_ledger"]["is_air_gapped"] is False
    assert body["egress_ledger"]["total_rows_sent"] is None
    assert "ran locally" not in body["egress_ledger"]["details"]
    assert server.RequestHandlerClass.orchestrator.llm_client.config.base_url.startswith("http://localhost")
