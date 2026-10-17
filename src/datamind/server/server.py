"""Lightweight HTTP server providing REST API and static UI serving for DataMind."""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from datamind.adapters.duckdb_adapter import DuckDBAdapter
from datamind.adapters.snowflake_adapter import SnowflakeAdapter
from datamind.agent.orchestrator import AgentOrchestrator
from datamind.config import AppConfig, load_config
from datamind.llm.budget import BudgetConfigError, BudgetExceeded
from datamind.llm.client import LLMClient
from datamind.retrieval.sqlite_fts import SQLiteFTSRetriever
from datamind.semantic.loader import load_semantic_model

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


class DataMindRequestHandler(BaseHTTPRequestHandler):
    """Handles HTTP requests for DataMind web UI and agent API."""

    orchestrator: AgentOrchestrator
    config: AppConfig
    backend_name: str

    def _set_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _send_json(self, status_code: int, data: dict[str, Any]) -> None:
        payload = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/health":
            self._send_json(200, {
                "status": "healthy",
                "service": "datamind",
                "version": "0.1.0",
                "backend": self.backend_name,
            })
            return

        if path == "/api/config":
            semantic_model = self.orchestrator.semantic_model
            tables = [
                {
                    "name": t.name,
                    "description": t.description,
                    "columns": [c.name for c in t.columns],
                }
                for t in semantic_model.tables
            ]
            sample_questions = [
                "Which products experienced the largest month-over-month revenue decline?",
                "Which products had revenue decline and what were customer complaints about them?",
                "What is the total sales revenue across all products in the database?",
                "What is the average order line amount across all sales?",
                "How many critical priority support tickets were logged?",
            ]
            self._send_json(200, {
                "backend": self.backend_name,
                "model_name": self.orchestrator.llm_client.config.orchestrator_model,
                "semantic_model": semantic_model.name,
                "default_currency": getattr(semantic_model, "default_currency", "USD"),
                "currency_symbol": getattr(semantic_model, "currency_symbol", "$"),
                "tables": tables,
                "sample_questions": sample_questions,
            })
            return

        # Serve static assets
        filename = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
        file_path = STATIC_DIR / filename

        if not file_path.exists() or not file_path.is_file():
            self.send_error(404, f"File not found: {path}")
            return

        content_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
        }
        content_type = content_types.get(file_path.suffix.lower(), "application/octet-stream")

        content = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/ask":
            self.send_error(404, "Endpoint not found")
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            self._send_json(400, {"error": "Missing request body"})
            return

        body_bytes = self.rfile.read(content_length)
        try:
            payload = json.loads(body_bytes.decode("utf-8"))
        except Exception as e:
            self._send_json(400, {"error": f"Invalid JSON body: {e}"})
            return

        question = payload.get("question", "").strip()
        if not question:
            self._send_json(400, {"error": "Question field is required"})
            return

        is_permissive = bool(payload.get("permissive", False))
        max_turns = int(payload.get("max_turns", self.config.agent.max_steps))

        try:
            result = self.orchestrator.run(question, max_turns=max_turns)
        except BudgetExceeded as e:
            logger.warning("Budget limit reached: %s", e)
            self._send_json(429, {
                "error_type": "budget_exceeded",
                "error": str(e),
                "message": f"Query halted by budget guard: {e}",
            })
            return
        except BudgetConfigError as e:
            logger.warning("Budget configuration error: %s", e)
            self._send_json(400, {
                "error_type": "budget_config_error",
                "error": str(e),
                "message": f"Configuration error: {e}",
            })
            return
        except Exception as e:
            logger.exception("Agent execution error")
            self._send_json(500, {"error": f"Execution error: {e}"})
            return

        is_strict = not is_permissive
        is_clean = result.citation_report.is_clean
        overall_success = result.success and (is_clean if is_strict else True)

        queries_data = [
            {
                "query_label": q.query_label,
                "query_id": q.result.query_id,
                "elapsed_ms": q.result.elapsed_ms,
                "sql": q.sql,
                "purpose": q.purpose,
                "columns": q.result.columns,
                "rows": q.result.rows,
                "truncated": q.result.truncated,
            }
            for q in result.evidence_store.queries
        ]

        chunks_data = [
            {
                "chunk_id": c.chunk_id,
                "doc_name": c.doc_name,
                "text": c.text,
                "score": round(c.score, 4),
                "metadata": c.metadata,
            }
            for c in result.evidence_store.chunks
        ]

        citations_data = [
            {
                "raw": c.raw,
                "target_id": c.target_id,
                "is_valid": c.is_valid,
                "evidence_type": c.evidence_type,
                "error": c.error,
            }
            for c in result.citation_report.citations
        ]

        numeric_checks_data = [
            {
                "raw_text": nc.raw_text,
                "claimed_value": nc.claimed_value,
                "sentence": nc.sentence,
                "status": nc.status,
                "row_id": nc.row_id,
                "matched_column": nc.matched_column,
                "cell_value": nc.cell_value,
                "message": nc.message,
            }
            for nc in result.citation_report.numeric_checks
        ]

        is_truncated = getattr(result, "is_truncated", False) or getattr(result.citation_report, "is_truncated", False)
        finish_reason = getattr(result, "finish_reason", None)

        response_data = {
            "question": result.question,
            "answer": result.answer,
            "success": overall_success and not is_truncated,
            "turns": result.turns,
            "error": result.error,
            "backend": self.backend_name,
            "is_truncated": is_truncated,
            "finish_reason": finish_reason,
            "citation_report": {
                "is_clean": is_clean and not is_truncated,
                "is_truncated": is_truncated,
                "valid_count": result.citation_report.valid_count,
                "invalid_count": result.citation_report.invalid_count,
                "verified_numbers_count": result.citation_report.verified_numbers_count,
                "discrepancy_count": result.citation_report.discrepancy_count,
                "unsupported_claims_count": result.citation_report.unsupported_claims_count,
                "citations": citations_data,
                "numeric_checks": numeric_checks_data,
            },
            "evidence": {
                "queries": queries_data,
                "chunks": chunks_data,
            },
        }

        self._send_json(200, response_data)


def create_server(
    config: AppConfig,
    backend: str | None = None,
    host: str = "0.0.0.0",
    port: int = 8000,
) -> tuple[ThreadingHTTPServer, Any, Any]:
    """Instantiate and configure ThreadingHTTPServer with initialized Agent."""
    semantic_model = load_semantic_model(config.semantic_model)
    backend_type = backend or config.backend.type

    if backend_type == "duckdb":
        adapter = DuckDBAdapter(
            db_path=config.backend.duckdb_path,
            read_only=True,
            max_rows=config.guardrails.max_rows,
        )
    elif backend_type == "snowflake":
        adapter = SnowflakeAdapter(
            config=config.backend.snowflake,
            max_rows=config.guardrails.max_rows,
            timeout_seconds=config.guardrails.statement_timeout_seconds,
        )
    else:
        raise ValueError(f"Unknown database backend: {backend_type}")

    retriever = SQLiteFTSRetriever(
        index_path=config.retrieval.index_path,
        source_db_path=config.backend.duckdb_path,
    )
    retriever.build_index()

    llm_client = LLMClient(config.llm)
    orchestrator = AgentOrchestrator(
        llm_client=llm_client,
        db_adapter=adapter,
        retriever=retriever,
        semantic_model=semantic_model,
    )

    class CustomHandler(DataMindRequestHandler):
        pass

    CustomHandler.orchestrator = orchestrator
    CustomHandler.config = config
    CustomHandler.backend_name = backend_type

    server = ThreadingHTTPServer((host, port), CustomHandler)
    return server, adapter, retriever


def start_server(
    config_path: str = "datamind.yaml",
    backend: str | None = None,
    host: str = "0.0.0.0",
    port: int = 8000,
) -> None:
    """Run DataMind HTTP server mainloop."""
    config = load_config(config_path)
    server, adapter, retriever = create_server(config=config, backend=backend, host=host, port=port)
    print("=" * 65)
    print("DATAMIND AGENT & INTERACTIVE WEB UI SERVER")
    print("=" * 65)
    print(f"Server URL:     http://localhost:{port}")
    print(f"Active Backend: {adapter.__class__.__name__} ({getattr(adapter, 'dialect', 'duckdb')})")
    print(f"Target Model:   {config.llm.orchestrator_model}")
    print(f"Semantic Model: {config.semantic_model}")
    print("Press Ctrl+C to stop server.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        server.server_close()
        adapter.close()
        retriever.close()
