"""Citation extraction, verification, and provenance checking against EvidenceStore."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from datamind.agent.evidence import EvidenceStore


@dataclass
class Citation:
    raw: str
    target_id: str
    is_valid: bool
    evidence_type: str       # "sql_row" | "document_chunk" | "unknown"
    resolved_data: Any = None
    error: str | None = None


@dataclass
class CitationReport:
    citations: list[Citation] = field(default_factory=list)
    valid_count: int = 0
    invalid_count: int = 0
    is_clean: bool = True

    def get_invalid_ids(self) -> list[str]:
        return [c.target_id for c in self.citations if not c.is_valid]


CITATION_PATTERN = re.compile(r"\[\[(Q\d+:R\d+|D:[a-zA-Z0-9_\-]+:[a-zA-Z0-9_\-]+)\]\]")
# Catch any potential attempted bracket citations that don't match the strict syntax
LOOSE_CITATION_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")


def verify_citations(text: str, evidence_store: EvidenceStore) -> CitationReport:
    """Extract and verify all [[Q<n>:R<m>]] and [[D:<doc>:<pk>]] citations in text."""
    report = CitationReport()
    seen_ids: set[str] = set()

    # Find all bracketed tokens [[...]]
    all_tokens = LOOSE_CITATION_PATTERN.findall(text)
    for raw_token in all_tokens:
        token = raw_token.strip()
        if token in seen_ids:
            continue
        seen_ids.add(token)

        raw_str = f"[[{token}]]"

        # Check if it matches strict syntax
        if not CITATION_PATTERN.fullmatch(raw_str):
            # Fabricated or malformed citation
            report.citations.append(
                Citation(
                    raw=raw_str,
                    target_id=token,
                    is_valid=False,
                    evidence_type="unknown",
                    error=f"Malformed citation syntax: '{token}'. Must be Q<n>:R<m> or D:<doc>:<pk>.",
                )
            )
            report.invalid_count += 1
            report.is_clean = False
            continue

        # Check if ID exists in EvidenceStore
        if not evidence_store.has_id(token):
            report.citations.append(
                Citation(
                    raw=raw_str,
                    target_id=token,
                    is_valid=False,
                    evidence_type="sql_row" if token.startswith("Q") else "document_chunk",
                    error=f"Fabricated citation: ID '{token}' was never produced by any executed tool.",
                )
            )
            report.invalid_count += 1
            report.is_clean = False
            continue

        # Resolve valid citation
        if token.startswith("Q"):
            row_data = evidence_store.get_row(token)
            report.citations.append(
                Citation(
                    raw=raw_str,
                    target_id=token,
                    is_valid=True,
                    evidence_type="sql_row",
                    resolved_data=row_data,
                )
            )
            report.valid_count += 1
        else:
            chunk = evidence_store.get_chunk(token)
            report.citations.append(
                Citation(
                    raw=raw_str,
                    target_id=token,
                    is_valid=True,
                    evidence_type="document_chunk",
                    resolved_data=chunk,
                )
            )
            report.valid_count += 1

    return report
