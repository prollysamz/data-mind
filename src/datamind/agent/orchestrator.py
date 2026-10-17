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
    is_truncated: bool = False
    finish_reason: str | None = None
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

    def _is_ambiguous(self, question: str) -> bool:
        """Classify if user query is underspecified or ambiguous (Section 8.3 Planner)."""
        q = question.strip().lower()
        ambiguous_patterns = [
            "how are the numbers looking",
            "how are numbers looking",
            "how's business",
            "how is business",
            "show me the numbers",
            "what are the numbers",
            "what's going on",
            "what is going on",
            "how are we doing",
            "tell me about the data",
            "show data",
            "give me numbers",
            "how are things",
            "status update on everything",
            "status update",
            "performance update",
            "any updates",
            "overall situation",
            "overview of recent trends",
            "how are our metrics",
            "give me an overview",
            "how is everything looking",
        ]
        return any(pat in q for pat in ambiguous_patterns)

    def run(
        self,
        question: str,
        max_turns: int = 6,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> AgentResult:
        """Execute end-to-end question answering loop."""
        # Reset evidence store per question unless continuing an active conversation
        if not conversation_history:
            self.evidence_store.clear()

        # Section 8.3 Planner: Handle ambiguous queries by asking for clarification
        if not conversation_history and self._is_ambiguous(question):
            clarification_msg = (
                "Could you please clarify which specific numbers you would like to examine? "
                "For example: total sales revenue across all products, month-over-month revenue decline, "
                "product catalog pricing, or customer support ticket breakdown?"
            )
            report = verify_citations(clarification_msg, self.evidence_store, self.semantic_model)
            return AgentResult(
                question=question,
                answer=clarification_msg,
                evidence_store=self.evidence_store,
                citation_report=report,
                turns=1,
                success=True,
                messages=[{"role": "assistant", "content": clarification_msg}],
            )

        system_prompt = build_system_prompt(self.semantic_model)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": question})

        turns_taken = 0
        total_tokens_consumed = 0
        sql_repairs_count = 0
        max_sql_repairs = getattr(self, "max_sql_repairs", 2)
        max_question_tokens = 32768

        for turn_idx in range(max_turns):
            turns_taken = turn_idx + 1
            reply = self.llm_client.chat(messages=messages, tools=TOOL_DEFINITIONS)

            # Track accumulated tokens
            usage_info = reply.get("usage", {})
            turn_tokens = usage_info.get("total_tokens", 0)
            total_tokens_consumed += turn_tokens

            if total_tokens_consumed > max_question_tokens:
                logger.warning("Question token cap exceeded (%d > %d)", total_tokens_consumed, max_question_tokens)
                return AgentResult(
                    question=question,
                    answer=f"Error: Question token cap exceeded ({total_tokens_consumed} tokens consumed, max allowed: {max_question_tokens}).",
                    evidence_store=self.evidence_store,
                    citation_report=CitationReport(is_clean=False),
                    turns=turns_taken,
                    success=False,
                    error="question_token_cap_exceeded",
                    messages=messages,
                )

            tool_calls = reply.get("tool_calls")
            if not tool_calls:
                # Model produced final answer
                final_text = reply.get("content") or ""
                finish_reason = reply.get("finish_reason")
                is_truncated = (finish_reason == "length")
                report = verify_citations(final_text, self.evidence_store, self.semantic_model)
                if is_truncated:
                    from datamind.agent.verifier import NumericCheck
                    report.is_truncated = True
                    report.is_clean = False
                    report.numeric_checks.append(
                        NumericCheck(
                            raw_text="[TRUNCATED]",
                            claimed_value=0.0,
                            sentence=final_text[-120:] if final_text else "Truncated output",
                            status="DISCREPANCY",
                            message="Answer generation truncated due to token limit (finish_reason=length).",
                        )
                    )
                    report.discrepancy_count += 1

                return AgentResult(
                    question=question,
                    answer=final_text,
                    evidence_store=self.evidence_store,
                    citation_report=report,
                    turns=turns_taken,
                    success=(not is_truncated),
                    is_truncated=is_truncated,
                    finish_reason=finish_reason,
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
                    if sql_repairs_count >= max_sql_repairs:
                        tool_results[call_id] = json.dumps({
                            "error": f"SQL repair limit ({max_sql_repairs}) reached. "
                            "Do not attempt further SQL queries. Synthesize your final answer from existing evidence."
                        })
                    else:
                        sql_query = args.get("sql", "")
                        purpose = args.get("purpose", "Analysis query")
                        out = execute_sql_tool(
                            sql=sql_query,
                            purpose=purpose,
                            guard=self.sql_guard,
                            adapter=self.db_adapter,
                            evidence_store=self.evidence_store,
                        )
                        if "error" in out:
                            sql_repairs_count += 1
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
