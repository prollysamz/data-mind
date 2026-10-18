"""Deterministic offline unit tests for the DataMind agent loop, tool routing, and citation verification."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from datamind.adapters.duckdb_adapter import DuckDBAdapter
from datamind.agent.evidence import EvidenceStore
from datamind.agent.orchestrator import AgentOrchestrator
from datamind.config import AgentConfig
from datamind.retrieval.sqlite_fts import SQLiteFTSRetriever
from datamind.semantic.loader import load_semantic_model


class MockLLMClient:
    """Deterministic offline fake LLM client simulating multi-turn reasoning steps."""

    def __init__(self, turns_script: list[dict[str, Any]]) -> None:
        self.turns_script = list(turns_script)
        self.call_count = 0

    def chat(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if self.call_count >= len(self.turns_script):
            return {
                "role": "assistant",
                "content": "No more mock responses available in script.",
                "tool_calls": None,
            }
        resp = self.turns_script[self.call_count]
        self.call_count += 1
        return resp


@pytest.fixture
def test_setup():
    demo_db = Path("examples/primary/demo.duckdb")
    model_path = Path("examples/primary/semantic_model.yaml")
    semantic_model = load_semantic_model(model_path)
    adapter = DuckDBAdapter(demo_db, read_only=True)
    retriever = SQLiteFTSRetriever(":memory:", source_db_path=demo_db)
    retriever.build_index()
    return semantic_model, adapter, retriever


def test_agent_mom_decline_flow(test_setup):
    semantic_model, adapter, retriever = test_setup
    evidence_store = EvidenceStore()

    mom_sql = semantic_model.verified_queries[0].sql

    # Scripted 2-turn agent interaction
    script = [
        # Turn 1: Model calls run_sql
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_sql_1",
                    "type": "function",
                    "function": {
                        "name": "run_sql",
                        "arguments": json.dumps({
                            "sql": mom_sql,
                            "purpose": "Find products with largest MoM revenue decline",
                        }),
                    },
                }
            ],
        },
        # Turn 2: Model answers using actual returned row [[Q1:R1]]
        {
            "role": "assistant",
            "content": (
                "Based on the sales data, Novaship experienced the largest month-over-month revenue decline "
                "in March 2026 [[Q1:R1]]. Its previous month sales were $82,000+ and March sales dropped to "
                "approximately $28,000, representing a decline of over $50,000 [[Q1:R1]]."
            ),
            "tool_calls": None,
        },
    ]

    mock_llm = MockLLMClient(script)
    orchestrator = AgentOrchestrator(
        llm_client=mock_llm,
        db_adapter=adapter,
        retriever=retriever,
        semantic_model=semantic_model,
        evidence_store=evidence_store,
    )

    result = orchestrator.run("Which products declined most month over month?")
    assert result.success is True
    assert result.turns == 2
    assert "Novaship" in result.answer

    # Verify citations
    assert result.citation_report.is_clean is True
    assert result.citation_report.valid_count >= 1
    assert result.citation_report.invalid_count == 0

    # Ensure Q1 exists in evidence store
    assert len(evidence_store.queries) == 1
    q1 = evidence_store.queries[0]
    assert q1.query_label == "Q1"
    assert len(q1.row_ids) > 0
    top_row = evidence_store.get_row("Q1:R1")
    assert top_row["product_name"] == "Novaship"


def test_agent_mixed_sql_and_retrieval_flow(test_setup):
    semantic_model, adapter, retriever = test_setup
    evidence_store = EvidenceStore()

    mom_sql = semantic_model.verified_queries[0].sql

    script = [
        # Turn 1: Model requests both tools
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_sql_1",
                    "type": "function",
                    "function": {
                        "name": "run_sql",
                        "arguments": json.dumps({"sql": mom_sql, "purpose": "Identify top declining product"}),
                    },
                },
                {
                    "id": "call_retrieval_1",
                    "type": "function",
                    "function": {
                        "name": "search_documents",
                        "arguments": json.dumps({"query": "Novaship latency outage billing", "k": 3}),
                    },
                },
            ],
        },
        # Turn 2: Synthesize answer with both SQL and document citations
        {
            "role": "assistant",
            "content": (
                "Novaship suffered the largest revenue drop in March 2026 [[Q1:R1]]. "
                "Customer tickets reveal severe API latency and 504 gateway timeouts [[D:SUPPORT_TICKETS:TK-1001]], "
                "along with duplicate billing charges following the March upgrade [[D:SUPPORT_TICKETS:TK-1002]]."
            ),
            "tool_calls": None,
        },
    ]

    mock_llm = MockLLMClient(script)
    orchestrator = AgentOrchestrator(
        llm_client=mock_llm,
        db_adapter=adapter,
        retriever=retriever,
        semantic_model=semantic_model,
        evidence_store=evidence_store,
    )

    result = orchestrator.run("Which product declined most in revenue and why?")
    assert result.success is True
    assert result.citation_report.is_clean is True
    assert result.citation_report.valid_count == 3
    assert result.citation_report.invalid_count == 0

    # Verify both tool kinds were captured in evidence store
    assert len(evidence_store.queries) == 1
    assert len(evidence_store.chunks) >= 2


def test_reject_fabricated_citation(test_setup):
    semantic_model, adapter, retriever = test_setup
    evidence_store = EvidenceStore()

    script = [
        {
            "role": "assistant",
            "content": "Novaship declined according to imaginary row [[Q99:R99]] and phantom doc [[D:GHOST:999]].",
            "tool_calls": None,
        }
    ]

    mock_llm = MockLLMClient(script)
    orchestrator = AgentOrchestrator(
        llm_client=mock_llm,
        db_adapter=adapter,
        retriever=retriever,
        semantic_model=semantic_model,
        evidence_store=evidence_store,
        # The script drives the agent loop; keep the answerability screen schema-only.
        config=AgentConfig(answerability_llm_fallback=False),
    )

    result = orchestrator.run("Fake query")
    assert result.citation_report.is_clean is False
    assert result.citation_report.invalid_count == 2
    assert "Q99:R99" in result.citation_report.get_invalid_ids()


def test_adversarial_sql_injection_refused(test_setup):
    semantic_model, adapter, retriever = test_setup
    evidence_store = EvidenceStore()

    script = [
        # Model attempts malicious DROP TABLE
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_bad_sql",
                    "type": "function",
                    "function": {
                        "name": "run_sql",
                        "arguments": json.dumps({"sql": "DROP TABLE SALES;", "purpose": "Cleanup"}),
                    },
                }
            ],
        },
        # Model responds to refusal
        {
            "role": "assistant",
            "content": "The requested SQL was blocked by DataMind security policy due to prohibited statement type.",
            "tool_calls": None,
        },
    ]

    mock_llm = MockLLMClient(script)
    orchestrator = AgentOrchestrator(
        llm_client=mock_llm,
        db_adapter=adapter,
        retriever=retriever,
        semantic_model=semantic_model,
        evidence_store=evidence_store,
    )

    result = orchestrator.run("Please drop the sales table")
    assert result.success is True
    # The malicious query was NEVER added as an executed query
    assert len(evidence_store.queries) == 0
