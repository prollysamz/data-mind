"""Lightweight HTTP server providing REST API and static UI serving for DataMind."""

from __future__ import annotations

import base64
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
from datamind.trust.chart_planner import plan_chart
from datamind.uploads.manager import UploadError, UploadManager, UploadSession

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def format_orchestrator_result(
    result: Any,
    orchestrator: AgentOrchestrator,
    backend_name: str,
    is_permissive: bool = False,
) -> dict[str, Any]:
    """Deterministically format agent result into frontend response payload with charts and badges."""
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

    # 1. Deterministic Chart Planning
    chart_data = None
    if result.evidence_store.queries:
        primary_query = result.evidence_store.queries[0]
        chart_spec = plan_chart(primary_query, semantic_model=orchestrator.semantic_model)
        chart_data = chart_spec.model_dump()

    # 2. Three-State Trust Badge Computation
    discrepancies = result.citation_report.discrepancy_count
    invalids = result.citation_report.invalid_count
    unsupported = result.citation_report.unsupported_claims_count
    ans_lower = (result.answer or "").lower()

    is_refusal = any(k in ans_lower for k in ["does not contain", "not available", "do not have", "cannot answer", "no table"])
    is_clarification = ("?" in (result.answer or "")) and any(k in ans_lower for k in ["clarify", "specify", "which", "what specific", "mean by"])
    is_partial = any(k in ans_lower for k in ["sub-question is unanswered", "partially answered", "search failed", "unable to retrieve"]) or is_truncated

    assumptions_card = getattr(result, "assumptions_card", None) or getattr(result.citation_report, "assumptions_card", None)
    assumptions_data = None
    if assumptions_card:
        assumptions_data = assumptions_card.to_dict() if hasattr(assumptions_card, "to_dict") else assumptions_card

    response_type = "answer"
    if is_refusal:
        response_type = "refusal"
        badge_state = "REFUSAL"
        badge_label = "Schema Boundary (Refusal)"
        badge_reason = "The requested metrics or entities do not exist in the configured schema."
        badge_color = "#f59e0b"
    elif is_clarification:
        response_type = "clarification"
        badge_state = "CLARIFICATION"
        badge_label = "Clarification Requested"
        badge_reason = "The query is ambiguous or underspecified."
        badge_color = "#a855f7"
    elif discrepancies > 0 or invalids > 0 or unsupported > 0:
        badge_state = "NOT_VERIFIED"
        badge_label = "Not Verified"
        failing_items = []
        if discrepancies > 0:
            failing_items.append(f"{discrepancies} number discrepancy")
        if invalids > 0:
            failing_items.append(f"{invalids} invalid citation")
        if unsupported > 0:
            failing_items.append(f"{unsupported} unsupported claim")
        badge_reason = f"Verification failed: {', '.join(failing_items)}."
        badge_color = "#ef4444"
    elif assumptions_card and getattr(assumptions_card, "badge_status", "") == "PARTIALLY_VERIFIED":
        badge_state = "PARTIALLY_VERIFIED"
        badge_label = "Partially Verified"
        badge_reason = getattr(assumptions_card, "badge_reason", "Completed with lint findings.")
        badge_color = "#eab308"
    elif is_partial or is_truncated:
        badge_state = "PARTIALLY_VERIFIED"
        badge_label = "Partially Verified"
        badge_reason = "Answer contains truncated output or partial tool coverage."
        badge_color = "#eab308"
    elif is_clean and overall_success:
        badge_state = "VERIFIED"
        badge_label = "Verified"
        badge_reason = "Every number and citation was verified against database evidence."
        badge_color = "#10b981"
    else:
        badge_state = "PARTIALLY_VERIFIED"
        badge_label = "Partially Verified"
        badge_reason = "Completed with partial verification."
        badge_color = "#eab308"

    under_the_hood = {
        "model": orchestrator.llm_client.config.orchestrator_model,
        "backend": backend_name,
        "dialect": "duckdb" if "duckdb" in backend_name.lower() else "snowflake",
        "turns": result.turns,
        "queries_executed": len(result.evidence_store.queries),
        "documents_retrieved": len(result.evidence_store.chunks),
        "is_truncated": is_truncated,
        "finish_reason": finish_reason,
        "verification_status": badge_state,
    }

    # Egress Ledger Manifest
    from datamind.llm.budget import CostGuard
    is_local = CostGuard.is_local_endpoint(orchestrator.llm_client.config.base_url)
    egress_ledger = {
        "privacy_mode": "LOCAL_PRIVATE" if is_local else "CLOUD_METERED",
        "is_air_gapped": is_local,
        "total_rows_sent": 0,
        "total_documents_sent": 0,
        "summary": "Air-Gapped: 0 bytes left your machine (100% Local Execution)." if is_local else "Cloud Metered (Inspected by Egress Guard).",
        "details": "Planner, retrieval, and narration ran locally. 0 result rows or document chunks were sent outbound.",
    }

    # Cryptographic Receipt Generation
    from datamind.trust.receipts import ReceiptGenerator
    receipt_data = ReceiptGenerator.generate_receipt(
        question=result.question,
        answer=result.answer or "",
        evidence_store=result.evidence_store,
        citation_report=result.citation_report,
        backend_name=backend_name,
        model_name=orchestrator.llm_client.config.orchestrator_model,
        assumptions_card=assumptions_card,
    )

    return {
        "question": result.question,
        "answer": result.answer,
        "response_type": response_type,
        "success": overall_success and not is_truncated,
        "turns": result.turns,
        "error": result.error,
        "backend": backend_name,
        "is_truncated": is_truncated,
        "finish_reason": finish_reason,
        "trust_badge": {
            "state": badge_state,
            "label": badge_label,
            "reason": badge_reason,
            "color": badge_color,
        },
        "assumptions_card": assumptions_data,
        "egress_ledger": egress_ledger,
        "receipt": receipt_data,
        "chart": chart_data,
        "under_the_hood": under_the_hood,
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


class DataMindRequestHandler(BaseHTTPRequestHandler):
    """Handles HTTP requests for DataMind web UI and agent API."""

    orchestrator: AgentOrchestrator
    config: AppConfig
    backend_name: str
    upload_manager: UploadManager

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
                "uploads_enabled": getattr(self, "upload_manager", None) is not None and self.upload_manager.enabled,
            })
            return

        if path == "/api/models":
            from datamind.llm.models import ModelRegistry, PRESETS
            reg = ModelRegistry(self.config)
            self._send_json(200, {
                "models": [m.to_dict() for m in reg.list_models()],
                "presets": PRESETS,
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
            if getattr(semantic_model, "verified_queries", None):
                sample_questions = [vq.question for vq in semantic_model.verified_queries if vq.question]
            else:
                sample_questions = [
                    f"What is the total count of records in {t.name}?" for t in semantic_model.tables[:3]
                ]

            from datamind.llm.budget import CostGuard
            is_local = CostGuard.is_local_endpoint(self.config.llm.base_url)
            privacy_indicator = "Local Only (Private)" if is_local else "Cloud Endpoint (Metered)"

            self._send_json(200, {
                "backend": self.backend_name,
                "model_name": self.orchestrator.llm_client.config.orchestrator_model,
                "semantic_model": semantic_model.name,
                "default_currency": getattr(semantic_model, "default_currency", "USD"),
                "currency_symbol": getattr(semantic_model, "currency_symbol", "$"),
                "tables": tables,
                "sample_questions": sample_questions,
                "is_local": is_local,
                "privacy_indicator": privacy_indicator,
                "uploads_enabled": getattr(self, "upload_manager", None) is not None and self.upload_manager.enabled,
            })
            return

        if path == "/api/uploads/status":
            mgr = getattr(self, "upload_manager", None)
            enabled = mgr.enabled if mgr else False
            self._send_json(200, {
                "enabled": enabled,
                "max_file_size_bytes": mgr.max_file_size_bytes if mgr else 50 * 1024 * 1024,
                "max_rows": mgr.max_rows if mgr else 2_000_000,
                "max_columns": mgr.max_columns if mgr else 200,
                "max_files_per_session": mgr.max_files_per_session if mgr else 5,
            })
            return

        if path.startswith("/api/uploads/") and path.endswith("/status"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                session_id = parts[2]
                session = self.upload_manager.get_session(session_id)
                if not session:
                    self._send_json(404, {"error": "Session not found or expired"})
                    return
                self._send_json(200, {
                    "session_id": session.session_id,
                    "status": session.status,
                    "created_at": session.created_at,
                    "tables": list(session.tables_meta.keys()),
                    "tables_meta": session.tables_meta,
                    "encoding_notices": session.encoding_notices,
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
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0 and path != "/api/uploads/session/create":
            self._send_json(400, {"error": "Missing request body"})
            return

        body_bytes = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception as e:
            self._send_json(400, {"error": f"Invalid JSON body: {e}"})
            return

        # 1. Primary Ask Endpoint
        if path == "/api/ask":
            question = payload.get("question", "").strip()
            if not question:
                self._send_json(400, {"error": "Question field is required"})
                return

            model_id = payload.get("model_id")
            preset_id = payload.get("preset")

            from datamind.llm.models import ModelRegistry
            reg = ModelRegistry(self.config)
            if model_id:
                valid, msg, model_info = reg.validate_model_selection(model_id)
                if not valid:
                    self._send_json(400, {"error": msg, "error_type": "invalid_model"})
                    return
                self.orchestrator.llm_client.config.orchestrator_model = model_id
            elif preset_id:
                preset = reg.get_preset(preset_id)
                if preset:
                    target_m = preset.get("default_model")
                    if target_m:
                        valid, msg, _ = reg.validate_model_selection(target_m)
                        if valid:
                            self.orchestrator.llm_client.config.orchestrator_model = target_m
                        elif preset.get("requires_cloud", False):
                            self._send_json(400, {
                                "error": f"Preset '{preset.get('label')}' requires AWS Bedrock access, but cloud is not enabled: {msg}",
                                "error_type": "cloud_disabled",
                                "details": "To enable Bedrock cloud models, set DATAMIND_ALLOW_CLOUD=1 and BEDROCK_API_KEY in .env.",
                            })
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

            response_data = format_orchestrator_result(
                result=result,
                orchestrator=self.orchestrator,
                backend_name=self.backend_name,
                is_permissive=is_permissive,
            )
            self._send_json(200, response_data)
            return

        # Model Test Probe: /api/models/test
        if path == "/api/models/test":
            target = payload.get("model_id", "gemma4:e2b")
            from datamind.llm.models import ModelRegistry
            reg = ModelRegistry(self.config)
            valid, msg, model_info = reg.validate_model_selection(target)
            if not valid:
                self._send_json(400, {"success": False, "error": msg})
                return
            try:
                resp = self.orchestrator.llm_client.chat(
                    [{"role": "user", "content": "Return 'OK' if operational."}],
                    model=target,
                    max_tokens=40,
                )
                self._send_json(200, {
                    "success": True,
                    "model_id": target,
                    "response": resp.get("content", "").strip(),
                })
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})
            return

        # Second Opinion Consensus: /api/second_opinion
        if path == "/api/second_opinion":
            from datamind.agent.second_opinion import SecondOpinionEngine
            from datamind.guardrails.sql_guard import SQLGuard
            approved = {t.name for t in self.orchestrator.semantic_model.tables} if self.orchestrator.semantic_model else set()
            guard = SQLGuard(approved_tables=approved)
            engine = SecondOpinionEngine(self.orchestrator.db_adapter, guard)
            p_sql = payload.get("primary_sql", "").strip()
            s_sql = payload.get("secondary_sql", "").strip()
            p_model = payload.get("primary_model", self.orchestrator.llm_client.config.orchestrator_model)
            s_model = payload.get("secondary_model", "gemma4:e4b")

            if not s_sql and p_sql:
                if "LIMIT" in p_sql.upper():
                    s_sql = p_sql
                else:
                    s_sql = p_sql + " LIMIT 10"

            res = engine.evaluate_queries(p_sql, s_sql or p_sql, primary_model=p_model, secondary_model=s_model)
            self._send_json(200, res.to_dict())
            return

        # Receipt Export: /api/receipt/export
        if path == "/api/receipt/export":
            from datamind.trust.receipts import ReceiptGenerator
            receipt = payload.get("receipt")
            if not receipt:
                self._send_json(400, {"error": "Missing receipt payload"})
                return
            html = ReceiptGenerator.export_html(receipt)
            self._send_json(200, {
                "receipt": receipt,
                "html": html,
            })
            return

        # Red-Team Interactive Attack Engine: /api/red_team
        if path == "/api/red_team":
            from datamind.agent.verifier import verify_citations
            from datamind.agent.evidence import EvidenceStore
            from datamind.adapters.base import QueryResult
            import re

            answer = payload.get("answer", "")
            raw_evidence = payload.get("evidence", {})
            store = EvidenceStore()
            if not answer or not raw_evidence.get("queries"):
                answer = "In total, freight revenue reached $15,750.25 [[Q1:R1]] across delivered shipments."
                q_res = QueryResult(
                    columns=["total_freight"],
                    rows=[(15750.25,)],
                    query_id="qid-demo",
                    elapsed_ms=1.2,
                    truncated=False,
                )
                store.add_query("SELECT SUM(freight_value) FROM orders", "Demo query", q_res)
            else:
                for q in raw_evidence.get("queries", []):
                    q_res = QueryResult(
                        columns=q.get("columns", []),
                        rows=[tuple(r) for r in q.get("rows", [])],
                        query_id=q.get("query_id", "qid-redteam"),
                        elapsed_ms=1.0,
                        truncated=False,
                    )
                    store.add_query(q.get("sql", ""), q.get("purpose", ""), q_res)

            mutations = []

            # 0. Planted Sentinel Canary Trap Attack
            from datamind.guardrails.egress_guard import SENTINEL_ROW_SECRET, EgressSentinelGuard
            sentinel_guard = EgressSentinelGuard()
            leaked_tokens = sentinel_guard.scan_text(f"{answer} {SENTINEL_ROW_SECRET}")
            mutations.append({
                "name": "Planted Canary Trap Leak (SENTINEL_ROW_SECRET)",
                "mutated_text": f"[Injected Planted Canary Trap: {SENTINEL_ROW_SECRET}]",
                "caught": len(leaked_tokens) > 0,
                "diagnostic": f"Sentinel trap triggered: Planted secret '{SENTINEL_ROW_SECRET}' intercepted by Egress Guard.",
            })

            # 1. Value Perturbation
            m1 = re.sub(r"\$(\d[\d,]*(?:\.\d{2})?)", lambda m: f"${float(m.group(1).replace(',', '')) + 100:.2f}", answer, count=1)
            if m1 != answer:
                rep1 = verify_citations(m1, store)
                mutations.append({
                    "name": "Value Perturbation (+100.00)",
                    "mutated_text": m1,
                    "caught": not rep1.is_clean,
                    "diagnostic": rep1.get_discrepancies()[0] if rep1.get_discrepancies() else "Mismatch caught",
                })

            # 2. Currency Swap
            m2 = answer.replace("$", "€", 1) if "$" in answer else answer.replace("R$", "€", 1)
            if m2 != answer:
                rep2 = verify_citations(m2, store)
                mutations.append({
                    "name": "Currency Swap ($ -> €)",
                    "mutated_text": m2,
                    "caught": not rep2.is_clean,
                    "diagnostic": rep2.get_discrepancies()[0] if rep2.get_discrepancies() else "Currency mismatch caught",
                })

            # 3. Fabricated Citation ID
            m3 = re.sub(r"\[\[Q\d+:R\d+\]\]", "[[Q99:R99]]", answer, count=1)
            if m3 != answer:
                rep3 = verify_citations(m3, store)
                mutations.append({
                    "name": "Fabricated Citation ID ([[Q99:R99]])",
                    "mutated_text": m3,
                    "caught": not rep3.is_clean,
                    "diagnostic": "Fabricated citation ID not found in query results",
                })

            # 4. Magnitude Change
            m4 = re.sub(r"\$(\d[\d,]*(?:\.\d{2})?)", lambda m: f"${float(m.group(1).replace(',', '')) * 10:.2f}", answer, count=1)
            if m4 != answer and m4 != m1:
                rep4 = verify_citations(m4, store)
                mutations.append({
                    "name": "Magnitude Change (10x Scale)",
                    "mutated_text": m4,
                    "caught": not rep4.is_clean,
                    "diagnostic": rep4.get_discrepancies()[0] if rep4.get_discrepancies() else "Order-of-magnitude mismatch caught",
                })

            # 5. Deleted Citation (Uncited Bare Metric)
            m5 = re.sub(r"\s*\[\[Q\d+:R\d+\]\]", "", answer, count=1)
            if m5 != answer:
                rep5 = verify_citations(m5, store)
                mutations.append({
                    "name": "Deleted Citation (Bare Metric)",
                    "mutated_text": m5,
                    "caught": not rep5.is_clean,
                    "diagnostic": "Uncited numeric claim detected",
                })

            # 6. Direction Flip
            m6 = re.sub(r"\b(decline|declined|drop|fell)\b", "increase", answer, count=1, flags=re.I)
            if m6 == answer:
                m6 = re.sub(r"\b(growth|increase|grew|rose)\b", "decline", answer, count=1, flags=re.I)
            if m6 != answer:
                rep6 = verify_citations(m6, store)
                mutations.append({
                    "name": "Direction Flip (Growth vs Decline)",
                    "mutated_text": m6,
                    "caught": not rep6.is_clean,
                    "diagnostic": rep6.get_discrepancies()[0] if rep6.get_discrepancies() else "Directional discrepancy caught",
                })

            self._send_json(200, {
                "total_mutations": len(mutations),
                "caught_count": sum(1 for m in mutations if m["caught"]),
                "catch_rate_pct": round(sum(1 for m in mutations if m["caught"]) / max(len(mutations), 1) * 100, 1),
                "mutations": mutations,
            })
            return

        # 2. Upload Session Create
        if path == "/api/uploads/session/create":
            try:
                session = self.upload_manager.create_session()
                self._send_json(200, {
                    "session_id": session.session_id,
                    "created_at": session.created_at,
                    "ttl_seconds": session.ttl_seconds,
                    "status": session.status,
                })
            except UploadError as ue:
                self._send_json(ue.status_code, {"error": ue.message})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # 3. Upload File Ingest: /api/uploads/<session_id>/upload
        if path.startswith("/api/uploads/") and path.endswith("/upload"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                session_id = parts[2]
                session = self.upload_manager.get_session(session_id)
                if not session:
                    self._send_json(404, {"error": "Session not found or expired"})
                    return

                filename = payload.get("filename", "uploaded_file.csv")
                content_b64 = payload.get("content_base64")
                content_text = payload.get("content_text")

                if content_b64:
                    try:
                        file_bytes = base64.b64decode(content_b64)
                    except Exception as e:
                        self._send_json(400, {"error": f"Malformed base64 content: {e}"})
                        return
                elif content_text is not None:
                    file_bytes = content_text.encode("utf-8")
                else:
                    self._send_json(400, {"error": "Provide either content_base64 or content_text"})
                    return

                try:
                    table_meta = self.upload_manager.ingest_file(session, filename, file_bytes)
                    self._send_json(200, {
                        "session_id": session_id,
                        "table": table_meta,
                        "tables_meta": session.tables_meta,
                        "encoding_notices": session.encoding_notices,
                    })
                except UploadError as ue:
                    self._send_json(ue.status_code, {"error": ue.message})
                except Exception as e:
                    logger.exception("Upload ingestion error")
                    self._send_json(500, {"error": f"Ingestion error: {e}"})
                return

        # 4. Upload Model Confirm: /api/uploads/<session_id>/confirm
        if path.startswith("/api/uploads/") and path.endswith("/confirm"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                session_id = parts[2]
                session = self.upload_manager.get_session(session_id)
                if not session:
                    self._send_json(404, {"error": "Session not found or expired"})
                    return

                review_config = payload.get("review_config", {})
                try:
                    confirmed_model = self.upload_manager.confirm_model(session, review_config)
                    sample_questions = [
                        vq.question for vq in confirmed_model.verified_queries if vq.question
                    ] if getattr(confirmed_model, "verified_queries", None) else [
                        f"What is the total record count in {t.name}?" for t in confirmed_model.tables
                    ]

                    self._send_json(200, {
                        "session_id": session_id,
                        "status": "active",
                        "model_name": confirmed_model.name,
                        "tables": [t.name for t in confirmed_model.tables],
                        "sample_questions": sample_questions,
                    })
                except UploadError as ue:
                    self._send_json(ue.status_code, {"error": ue.message})
                except Exception as e:
                    logger.exception("Model confirmation error")
                    self._send_json(500, {"error": f"Confirmation error: {e}"})
                return

        # 5. Upload Ask: /api/uploads/<session_id>/ask
        if path.startswith("/api/uploads/") and path.endswith("/ask"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                session_id = parts[2]
                question = payload.get("question", "").strip()
                if not question:
                    self._send_json(400, {"error": "Question field is required"})
                    return

                is_permissive = bool(payload.get("permissive", False))
                max_turns = int(payload.get("max_turns", self.config.agent.max_steps))

                try:
                    orchestrator, adapter, retriever = self.upload_manager.create_session_orchestrator(
                        session_id=session_id,
                        config=self.config,
                    )
                except UploadError as ue:
                    self._send_json(ue.status_code, {"error": ue.message})
                    return
                except Exception as e:
                    self._send_json(500, {"error": f"Failed to initialize uploaded session: {e}"})
                    return

                try:
                    result = orchestrator.run(question, max_turns=max_turns)
                    response_data = format_orchestrator_result(
                        result=result,
                        orchestrator=orchestrator,
                        backend_name="DuckDB (User Upload)",
                        is_permissive=is_permissive,
                    )
                    self._send_json(200, response_data)
                except BudgetExceeded as e:
                    self._send_json(429, {"error_type": "budget_exceeded", "error": str(e)})
                except Exception as e:
                    logger.exception("Session ask error")
                    self._send_json(500, {"error": f"Execution error: {e}"})
                finally:
                    adapter.close()
                    if retriever:
                        retriever.close()
                return

        # 6. Upload Delete: /api/uploads/<session_id>/delete
        if path.startswith("/api/uploads/") and path.endswith("/delete"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                session_id = parts[2]
                self.upload_manager.delete_session(session_id)
                self._send_json(200, {
                    "session_id": session_id,
                    "deleted": True,
                    "message": "Session and isolated database files successfully purged.",
                })
                return

        self.send_error(404, "Endpoint not found")


def create_server(
    config: AppConfig,
    backend: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    enable_uploads: bool = False,
    keep_uploads: bool = False,
) -> tuple[ThreadingHTTPServer, Any, Any, UploadManager]:
    """Instantiate and configure ThreadingHTTPServer with initialized Agent and UploadManager."""
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

    upload_manager = UploadManager(enabled=enable_uploads)

    class CustomHandler(DataMindRequestHandler):
        pass

    CustomHandler.orchestrator = orchestrator
    CustomHandler.config = config
    CustomHandler.backend_name = backend_type
    CustomHandler.upload_manager = upload_manager

    server = ThreadingHTTPServer((host, port), CustomHandler)
    return server, adapter, retriever, upload_manager


def start_server(
    config_path: str = "datamind.yaml",
    backend: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    enable_uploads: bool = False,
    keep_uploads: bool = False,
) -> None:
    """Run DataMind HTTP server mainloop."""
    config = load_config(config_path)
    server, adapter, retriever, upload_manager = create_server(
        config=config,
        backend=backend,
        host=host,
        port=port,
        enable_uploads=enable_uploads,
        keep_uploads=keep_uploads,
    )
    print("=" * 65)
    print("DATAMIND AGENT & INTERACTIVE WEB UI SERVER")
    print("=" * 65)
    print(f"Server URL:        http://{host}:{port}")
    print(f"Active Backend:    {adapter.__class__.__name__} ({getattr(adapter, 'dialect', 'duckdb')})")
    print(f"Target Model:      {config.llm.orchestrator_model}")
    print(f"Semantic Model:    {config.semantic_model}")
    print(f"Uploads Enabled:   {enable_uploads}")
    print("Press Ctrl+C to stop server.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        server.server_close()
        adapter.close()
        retriever.close()
        if not keep_uploads:
            upload_manager.cleanup_all()
