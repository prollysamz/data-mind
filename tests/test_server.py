"""Unit tests for DataMind web server and REST API."""

import json
import threading
import time
from http.client import HTTPConnection
from urllib.request import Request, urlopen
import pytest

from datamind.config import load_config
from datamind.server.server import MAX_HTTP_BODY_BYTES, create_server


@pytest.fixture(scope="module")
def server_url():
    """Start test server on an ephemeral port and tear down after tests."""
    config = load_config("datamind.yaml")
    server, adapter, retriever, upload_mgr = create_server(config, backend="duckdb", host="127.0.0.1", port=0, enable_uploads=True)
    assigned_port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    url = f"http://127.0.0.1:{assigned_port}"
    yield url

    server.shutdown()
    server.server_close()
    adapter.close()
    retriever.close()
    upload_mgr.cleanup_all()


def test_server_health_endpoint(server_url):
    with urlopen(f"{server_url}/api/health") as res:
        assert res.status == 200
        data = json.loads(res.read().decode("utf-8"))
        assert data["status"] == "healthy"
        assert data["service"] == "datamind"
        assert data["backend"] == "duckdb"


def test_server_config_endpoint(server_url):
    with urlopen(f"{server_url}/api/config") as res:
        assert res.status == 200
        data = json.loads(res.read().decode("utf-8"))
        assert "tables" in data
        assert len(data["tables"]) >= 1
        assert "sample_questions" in data
        assert data["default_currency"] == "USD"
        assert data["currency_symbol"] == "$"


def test_server_static_assets(server_url):
    # HTML root
    with urlopen(f"{server_url}/") as res:
        assert res.status == 200
        content = res.read().decode("utf-8")
        assert "<!DOCTYPE html>" in content
        assert "DataMind" in content

    # CSS
    with urlopen(f"{server_url}/index.css") as res:
        assert res.status == 200
        content = res.read().decode("utf-8")
        assert "--accent-cyan" in content

    # JS
    with urlopen(f"{server_url}/app.js") as res:
        assert res.status == 200
        content = res.read().decode("utf-8")
        assert "executeQuery" in content
        assert "let formatted = escapeHtml(text)" in content
        assert "const rows = q.rows || []" in content


def test_server_blocks_static_path_traversal(server_url):
    host_port = server_url.removeprefix("http://")
    connection = HTTPConnection(host_port)
    try:
        connection.request("GET", "/../../../../README.md")
        response = connection.getresponse()
        assert response.status == 404
        assert b"DataMind: Verifiable Enterprise AI Data Agent" not in response.read()
    finally:
        connection.close()


def test_server_rejects_oversized_request_before_reading_body(server_url):
    host_port = server_url.removeprefix("http://")
    connection = HTTPConnection(host_port)
    try:
        connection.putrequest("POST", "/api/ask")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(MAX_HTTP_BODY_BYTES + 1))
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 413
    finally:
        connection.close()


def test_server_does_not_allow_cross_origin_browser_access(server_url):
    req = Request(
        f"{server_url}/api/health",
        headers={"Origin": "https://attacker.example"},
    )
    with urlopen(req) as res:
        assert res.headers.get("Access-Control-Allow-Origin") is None


def test_server_rejects_untrusted_host_header(server_url):
    host_port = server_url.removeprefix("http://")
    connection = HTTPConnection(host_port)
    try:
        connection.putrequest("GET", "/api/health", skip_host=True)
        connection.putheader("Host", "attacker.example")
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 421
    finally:
        connection.close()


def test_server_ask_validation_error(server_url):
    req = Request(
        f"{server_url}/api/ask",
        data=json.dumps({"question": ""}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(Exception) as exc:
        urlopen(req)
    assert "400" in str(exc.value)


@pytest.mark.parametrize("max_turns", ["not-a-number", 0, 999])
def test_server_rejects_invalid_max_turns(server_url, max_turns):
    req = Request(
        f"{server_url}/api/ask",
        data=json.dumps({"question": "test", "max_turns": max_turns}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(Exception) as exc:
        urlopen(req)
    assert "400" in str(exc.value)


def test_server_runs_questions_one_at_a_time(monkeypatch):
    """Concurrent /api/ask requests must not overlap on the shared orchestrator."""
    import datamind.server.server as server_mod

    config = load_config("datamind.yaml")
    server, adapter, retriever, upload_mgr = create_server(
        config, backend="duckdb", host="127.0.0.1", port=0, enable_uploads=False
    )
    state = {"in_flight": 0, "max_in_flight": 0}
    counter_lock = threading.Lock()

    def fake_run(question, max_turns=6):
        with counter_lock:
            state["in_flight"] += 1
            state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
        time.sleep(0.2)
        with counter_lock:
            state["in_flight"] -= 1
        return object()

    monkeypatch.setattr(server.RequestHandlerClass.orchestrator, "run", fake_run)
    monkeypatch.setattr(server_mod, "format_orchestrator_result", lambda **kwargs: {"ok": True})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/api/ask"

    def ask():
        req = Request(url, data=json.dumps({"question": "q"}).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req) as res:
            assert res.status == 200

    try:
        workers = [threading.Thread(target=ask) for _ in range(3)]
        for w in workers:
            w.start()
        for w in workers:
            w.join(timeout=10)
        assert state["max_in_flight"] == 1
    finally:
        server.shutdown()
        server.server_close()
        adapter.close()
        retriever.close()
        upload_mgr.cleanup_all()
