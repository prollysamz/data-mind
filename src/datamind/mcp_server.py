"""Model Context Protocol (MCP) stdio server for DataMind.

Exposes verifiable data agent tools (`datamind_ask`, `datamind_list_tables`, `datamind_describe_table`)
over standard JSON-RPC 2.0 stdio protocol.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from datamind.adapters.duckdb_adapter import DuckDBAdapter
from datamind.agent.orchestrator import AgentOrchestrator
from datamind.config import load_config
from datamind.guardrails.sql_guard import SQLGuard
from datamind.llm.client import LLMClient
from datamind.retrieval.sqlite_fts import SQLiteFTSRetriever
from datamind.semantic.loader import load_semantic_model


def get_tool_definitions() -> list[dict[str, Any]]:
    """Return MCP tool schemas."""
    return [
        {
            "name": "datamind_ask",
            "description": "Ask a natural language analytical question. Returns deterministic answer with verified provenance citations and chart recommendations.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The analytical or operational question to answer (e.g. 'Which products had revenue declines?')"
                    }
                },
                "required": ["question"]
            }
        },
        {
            "name": "datamind_list_tables",
            "description": "List all verified tables and metrics available in the active semantic model.",
            "inputSchema": {
                "type": "object",
                "properties": {}
            }
        },
        {
            "name": "datamind_describe_table",
            "description": "Get column descriptions, types, and primary keys for an approved table.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "Name of the table to describe"
                    }
                },
                "required": ["table_name"]
            }
        }
    ]


class DataMindMCPServer:
    """JSON-RPC 2.0 MCP server over stdin/stdout."""

    def __init__(self, config_path: str = "datamind.yaml") -> None:
        self.config = load_config(config_path)
        self.semantic_model = load_semantic_model(self.config.semantic_model)
        self.adapter = DuckDBAdapter(
            db_path=self.config.backend.duckdb_path,
            read_only=True,
            max_rows=self.config.guardrails.max_rows,
        )
        self.retriever = SQLiteFTSRetriever(
            index_path=self.config.retrieval.index_path,
            source_db_path=self.config.retrieval_source_path(),
        )
        self.guard = SQLGuard(
            approved_tables=self.semantic_model.get_approved_table_names(),
            dialect=self.adapter.dialect,
        )
        self.llm_client = LLMClient(self.config.llm, purpose="ask")
        self.orchestrator = AgentOrchestrator(
            llm_client=self.llm_client,
            db_adapter=self.adapter,
            retriever=self.retriever,
            semantic_model=self.semantic_model,
            sql_guard=self.guard,
        )

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Process incoming JSON-RPC request and return response."""
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {
                        "name": "datamind-mcp-server",
                        "version": "0.1.0"
                    },
                    "capabilities": {
                        "tools": {}
                    }
                }
            }

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": get_tool_definitions()
                }
            }

        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments", {})

            if name == "datamind_ask":
                question = arguments.get("question", "")
                res = self.orchestrator.run(question)
                content_text = (
                    f"{res.answer}\n\n"
                    f"--- Verification Status: {'VERIFIED' if res.citation_report.is_clean else 'FLAGGED'} "
                    f"({res.citation_report.verified_numbers_count} numbers verified, "
                    f"{res.citation_report.discrepancy_count} discrepancies) ---"
                )
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": content_text}
                        ],
                        "isError": not res.success
                    }
                }

            elif name == "datamind_list_tables":
                tables_info = [
                    {"table": t.name, "description": t.description}
                    for t in self.semantic_model.tables
                ]
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": json.dumps(tables_info, indent=2)}
                        ]
                    }
                }

            elif name == "datamind_describe_table":
                t_name = arguments.get("table_name", "").strip().lower()
                matched = next((t for t in self.semantic_model.tables if t.name.lower() == t_name), None)
                if not matched:
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": f"Table '{t_name}' not found in approved model."}],
                            "isError": True
                        }
                    }

                cols_info = [
                    {"name": c.name, "type": c.type, "description": c.description}
                    for c in matched.columns
                ]
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": json.dumps(cols_info, indent=2)}
                        ]
                    }
                }

            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method or tool '{name}' not found"
                    }
                }

        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method '{method}' not found"
                }
            }

    def run_stdio(self) -> None:
        """Run stdio loop reading JSON-RPC lines."""
        for line in sys.stdin:
            line_str = line.strip()
            if not line_str:
                continue
            try:
                req = json.loads(line_str)
                resp = self.handle_request(req)
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
            except Exception as e:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error or exception: {e}"}
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    server = DataMindMCPServer()
    server.run_stdio()
