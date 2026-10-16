"""Unit tests for DataMind web server and REST API."""

import json
import threading
import time
from urllib.request import Request, urlopen
import pytest

from datamind.config import load_config
from datamind.server.server import create_server


@pytest.fixture(scope="module")
def server_url():
    """Start test server on an ephemeral port and tear down after tests."""
    config = load_config("datamind.yaml")
    server, adapter, retriever = create_server(config, backend="duckdb", host="127.0.0.1", port=0)
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
