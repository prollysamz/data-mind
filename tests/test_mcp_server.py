"""Unit tests for DataMind MCP stdio server."""

import json
from unittest.mock import patch

from datamind.mcp_server import DataMindMCPServer, get_tool_definitions


def test_mcp_tool_definitions():
    tools = get_tool_definitions()
    tool_names = [t["name"] for t in tools]
    assert "datamind_ask" in tool_names
    assert "datamind_list_tables" in tool_names
    assert "datamind_describe_table" in tool_names


def test_mcp_honors_snowflake_backend_instead_of_opening_local_database():
    from datamind.config import load_config

    config = load_config("datamind_snowflake.yaml")
    with (
        patch("datamind.mcp_server.load_config", return_value=config),
        patch("datamind.mcp_server.SnowflakeAdapter") as snowflake,
        patch("datamind.mcp_server.DuckDBAdapter") as local,
    ):
        snowflake.return_value.dialect = "snowflake"
        server = DataMindMCPServer("datamind_snowflake.yaml")
    snowflake.assert_called_once()
    local.assert_not_called()
    assert server.orchestrator.db_adapter is snowflake.return_value
    assert server.orchestrator.config == config.agent
    server.retriever.close()


def test_mcp_initialize():
    server = DataMindMCPServer()
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {}
    }
    resp = server.handle_request(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert "result" in resp
    assert resp["result"]["serverInfo"]["name"] == "datamind-mcp-server"


def test_mcp_tools_list():
    server = DataMindMCPServer()
    req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {}
    }
    resp = server.handle_request(req)
    assert "result" in resp
    tools = resp["result"]["tools"]
    assert len(tools) == 3


def test_mcp_list_tables():
    server = DataMindMCPServer()
    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "datamind_list_tables",
            "arguments": {}
        }
    }
    resp = server.handle_request(req)
    assert "result" in resp
    content = resp["result"]["content"][0]["text"]
    tables = json.loads(content)
    table_names = [t["table"] for t in tables]
    assert "SALES" in table_names
    assert "PRODUCTS" in table_names
    assert "SUPPORT_TICKETS" in table_names


def test_mcp_describe_table():
    server = DataMindMCPServer()
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "datamind_describe_table",
            "arguments": {"table_name": "PRODUCTS"}
        }
    }
    resp = server.handle_request(req)
    assert "result" in resp
    content = resp["result"]["content"][0]["text"]
    cols = json.loads(content)
    col_names = [c["name"] for c in cols]
    assert "product_name" in col_names
    assert "base_price" in col_names
