"""Agent tool definitions and execution handlers."""

from __future__ import annotations

import json
from typing import Any
from datamind.adapters.base import DBAdapter
from datamind.agent.evidence import EvidenceStore
from datamind.guardrails.sql_guard import SQLGuard, SQLSecurityError
from datamind.retrieval.base import Retriever

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": (
                "Execute a read-only SQL query against the database to fetch structured data, metrics, and trends. "
                "Query will be checked by SQL safety guard. Use verified metrics and tables from the semantic model."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "The SQL query to execute. Must be a valid read-only SELECT query matching the approved semantic model.",
                    },
                    "purpose": {
                        "type": "string",
                        "description": "Brief explanation of what business question or hypothesis this SQL query answers.",
                    },
                },
                "required": ["sql", "purpose"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": (
                "Search customer support tickets, outage reports, and qualitative documentation using full-text search."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search keywords or natural language terms to search for in support tickets and documents.",
                    },
                    "k": {
                        "type": "integer",
                        "description": "Maximum number of document chunks to retrieve (default 5).",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


def execute_sql_tool(
    sql: str,
    purpose: str,
    guard: SQLGuard,
    adapter: DBAdapter,
    evidence_store: EvidenceStore,
) -> str:
    """Validate, execute, and store SQL query results, returning Markdown table with row IDs."""
    # 1. SQL Guard validation
    try:
        sanitized_sql = guard.validate(sql)
    except SQLSecurityError as e:
        return json.dumps({
            "error": "SQLSecurityError",
            "message": e.message,
            "violation_type": e.violation_type,
        })
    except Exception as e:
        return json.dumps({"error": "SQLValidationError", "message": str(e)})

    # 2. Database execution
    try:
        query_result = adapter.execute(sanitized_sql)
    except Exception as e:
        return json.dumps({"error": "DatabaseExecutionError", "message": str(e)})

    # 3. Add to evidence store
    query_label = evidence_store.add_query(
        sql=sanitized_sql,
        purpose=purpose,
        result=query_result,
    )

    # 4. Format output for LLM with citations
    lines: list[str] = [
        f"Query {query_label} (ID: {query_result.query_id}, Elapsed: {query_result.elapsed_ms:.1f}ms, Rows: {len(query_result.rows)}):",
    ]
    if not query_result.rows:
        lines.append("No rows returned.")
        return "\n".join(lines)

    # Header with RowID column
    header = ["RowID"] + query_result.columns
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * len(header)) + " |")

    # Format rows up to 15 rows for LLM context window
    for idx, row in enumerate(query_result.rows[:15], start=1):
        row_id = f"[[{query_label}:R{idx}]]"
        row_str = [row_id] + [str(val) for val in row]
        lines.append("| " + " | ".join(row_str) + " |")

    if len(query_result.rows) > 15:
        lines.append(f"... and {len(query_result.rows) - 15} more rows.")

    return "\n".join(lines)


def execute_retrieval_tool(
    query: str,
    k: int,
    retriever: Retriever,
    evidence_store: EvidenceStore,
) -> str:
    """Search documents, store chunks in EvidenceStore, and return Markdown summary."""
    try:
        chunks = retriever.search(query=query, k=k)
    except Exception as e:
        return json.dumps({"error": "RetrievalError", "message": str(e)})

    evidence_store.add_chunks(search_query=query, chunks=chunks)

    if not chunks:
        return f"No documents found matching query: '{query}'."

    lines: list[str] = [f"Retrieved {len(chunks)} document chunks for query '{query}':\n"]
    for chunk in chunks:
        lines.append(f"### [[{chunk.chunk_id}]] ({chunk.doc_name})")
        lines.append(f"Score: {chunk.score}")
        lines.append(f"{chunk.text}\n")

    return "\n".join(lines)
