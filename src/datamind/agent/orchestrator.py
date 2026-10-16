"""Agent orchestrator managing multi-turn planning, tool execution, and citation verification."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from typing import Any

from datamind.adapters.base import DBAdapter
from datamind.agent.evidence import EvidenceStore
from datamind.agent.prompts import build_system_prompt
from datamind.agent.tools import (
    TOOL_DEFINITIONS,
    execute_retrieval_tool,
    execute_sql_tool,
)
from datamind.agent.verifier import CitationReport, verify_citations
from datamind.guardrails.sql_guard import SQLGuard
from datamind.llm.client import LLMClient, build_tool_messages
from datamind.retrieval.base import Retriever
from datamind.semantic.model import SemanticModel

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    question: str
    answer: str
    evidence_store: EvidenceStore
    citation_report: CitationReport
    turns: int
    success: bool
    error: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)


class AgentOrchestrator:
    """Multi-turn data agent coordinating tool selection, execution, and deterministic grounding."""

    def __init__(
        self,
        llm_client: LLMClient,
        db_adapter: DBAdapter,
        retriever: Retriever,
        semantic_model: SemanticModel,
        sql_guard: SQLGuard | None = None,
        evidence_store: EvidenceStore | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.db_adapter = db_adapter
        self.retriever = retriever
        self.semantic_model = semantic_model
        self.evidence_store = evidence_store or EvidenceStore()

        approved_tables = semantic_model.get_approved_table_names()
        self.sql_guard = sql_guard or SQLGuard(
            approved_tables=approved_tables,
            dialect=db_adapter.dialect,
        )

    def run(
        self,
        question: str,
        max_turns: int = 6,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> AgentResult:
        """Execute end-to-end question answering loop."""
        system_prompt = build_system_prompt(self.semantic_model)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": question})

        turns_taken = 0
        for turn_idx in range(max_turns):
            turns_taken = turn_idx + 1
            reply = self.llm_client.chat(messages=messages, tools=TOOL_DEFINITIONS)

            tool_calls = reply.get("tool_calls")
            if not tool_calls:
                # Model produced final answer
                final_text = reply.get("content") or ""
                report = verify_citations(final_text, self.evidence_store, self.semantic_model)
                return AgentResult(
                    question=question,
                    answer=final_text,
                    evidence_store=self.evidence_store,
                    citation_report=report,
                    turns=turns_taken,
                    success=True,
                    messages=messages,
                )

            # Process tool calls
            tool_results: dict[str, str] = {}
            for call in tool_calls:
                call_id = call["id"]
                fn_name = call["function"]["name"]
                raw_args = call["function"]["arguments"]

                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except Exception as e:
                    args = {}
                    tool_results[call_id] = json.dumps({"error": f"Failed to parse arguments JSON: {e}"})
                    continue

                if fn_name == "run_sql":
                    sql_query = args.get("sql", "")
                    purpose = args.get("purpose", "Analysis query")
                    out = execute_sql_tool(
                        sql=sql_query,
                        purpose=purpose,
                        guard=self.sql_guard,
                        adapter=self.db_adapter,
                        evidence_store=self.evidence_store,
                    )
                    tool_results[call_id] = out

                elif fn_name == "search_documents":
                    query_terms = args.get("query", "")
                    k = int(args.get("k", 5))
                    out = execute_retrieval_tool(
                        query=query_terms,
                        k=k,
                        retriever=self.retriever,
                        evidence_store=self.evidence_store,
                    )
                    tool_results[call_id] = out

                else:
                    tool_results[call_id] = json.dumps({"error": f"Unknown tool: '{fn_name}'"})

            # Append assistant message with tool calls
            messages.append({
                "role": "assistant",
                "content": reply.get("content"),
                "tool_calls": tool_calls,
            })

            # Append tool outputs
            tool_messages = build_tool_messages(reply, tool_results)
            messages.extend(tool_messages)

        # Exceeded turns
        return AgentResult(
            question=question,
            answer="Error: Maximum reasoning iterations reached without concluding final answer.",
            evidence_store=self.evidence_store,
            citation_report=CitationReport(is_clean=False),
            turns=turns_taken,
            success=False,
            error="max_turns_exceeded",
            messages=messages,
        )
