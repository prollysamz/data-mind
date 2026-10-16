"""Citation extraction, deterministic numeric consistency checking, and provenance verification."""

from __future__ import annotations

from dataclasses import dataclass, field
import decimal
import re
from typing import Any, Literal

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
class NumericCheck:
    raw_text: str
    claimed_value: float
    sentence: str
    status: Literal["VERIFIED", "DISCREPANCY", "UNSUPPORTED"]
    row_id: str | None = None
    matched_column: str | None = None
    cell_value: Any = None
    message: str = ""


@dataclass
class CitationReport:
    citations: list[Citation] = field(default_factory=list)
    numeric_checks: list[NumericCheck] = field(default_factory=list)
    valid_count: int = 0
    invalid_count: int = 0
    verified_numbers_count: int = 0
    discrepancy_count: int = 0
    unsupported_claims_count: int = 0
    is_clean: bool = True

    def get_invalid_ids(self) -> list[str]:
        return [c.target_id for c in self.citations if not c.is_valid]

    def get_discrepancies(self) -> list[str]:
        return [nc.message for nc in self.numeric_checks if nc.status == "DISCREPANCY"]

    def get_unsupported_claims(self) -> list[str]:
        return [nc.message for nc in self.numeric_checks if nc.status == "UNSUPPORTED"]


CITATION_PATTERN = re.compile(r"\[\[(Q\d+:R\d+|D:[a-zA-Z0-9_\-]+:[a-zA-Z0-9_\-]+)\]\]")
LOOSE_CITATION_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")

# Matches currency numbers, decimals, or integers: e.g. $738,876.88, £22.20, 53,803.23, 11.10, 6, 42.5%
NUMERIC_PATTERN = re.compile(
    r"(?:[\$£€]\s*)?((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?:%|percent)?"
)


def _parse_float(val: Any) -> float | None:
    """Safely convert cell value or string to float."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, decimal.Decimal):
        return float(val)
    clean_str = str(val).replace(",", "").replace("$", "").replace("£", "").replace("€", "").strip()
    try:
        return float(clean_str)
    except (ValueError, TypeError):
        return None


def _is_calendar_or_bullet(raw_num_str: str, sentence: str, match_start: int) -> bool:
    """Detect if number is a bullet point (e.g. '1.') or calendar year (e.g. 2011, 2026)."""
    # Check if number is an isolated year (1900 - 2099)
    if re.fullmatch(r"\d{4}", raw_num_str):
        num_val = int(raw_num_str)
        if 1900 <= num_val <= 2099:
            return True

    # Check if number is a list bullet: '1. ', '2. ', '3) ' at line or segment start
    prefix = sentence[:match_start].strip()
    if prefix in ("", "*", "-", "•") and (match_start + len(raw_num_str) < len(sentence)):
        next_char = sentence[match_start + len(raw_num_str)]
        if next_char in (".", ")", ":"):
            return True

    return False


def verify_citations(text: str, evidence_store: EvidenceStore) -> CitationReport:
    """Extract and verify all citations and perform deterministic numeric reconciliation."""
    report = CitationReport()
    seen_citation_ids: set[str] = set()

    # 1. Provenance Verification
    all_bracket_tokens = LOOSE_CITATION_PATTERN.findall(text)
    for raw_token in all_bracket_tokens:
        token = raw_token.strip()
        if token in seen_citation_ids:
            continue
        seen_citation_ids.add(token)

        raw_str = f"[[{token}]]"

        # Check strict syntax
        if not CITATION_PATTERN.fullmatch(raw_str):
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

        # Valid citation
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

    # 2. Deterministic Numeric Consistency Verification
    # Break text into sentence/line segments
    segments = [s.strip() for s in re.split(r"[\n\r]+|\.\s+", text) if s.strip()]

    for segment in segments:
        # Find citations in this segment
        all_segment_citations = [
            c_id for c_id in CITATION_PATTERN.findall(segment)
            if evidence_store.has_id(c_id)
        ]
        row_citations = [c for c in all_segment_citations if c.startswith("Q")]
        doc_citations = [c for c in all_segment_citations if c.startswith("D")]

        # Strip citations and full dates (YYYY-MM-DD) before looking for claimed numbers
        cleaned_segment = LOOSE_CITATION_PATTERN.sub("", segment)
        cleaned_segment = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", cleaned_segment)
        cleaned_segment = re.sub(r"\b\d{4}-\d{2}\b", "", cleaned_segment)

        # Detect inequality / approximation modifiers in segment
        has_lower_bound = bool(re.search(r"\b(?:over|more than|exceeding|above|\+)\b", segment, re.I))

        for match in NUMERIC_PATTERN.finditer(cleaned_segment):
            raw_matched_num = match.group(1).replace(",", "")
            claimed_float = _parse_float(raw_matched_num)
            if claimed_float is None:
                continue

            # Skip calendar years or list bullets
            if _is_calendar_or_bullet(raw_matched_num, cleaned_segment, match.start()):
                continue

            matched = False
            matched_id = None
            matched_col_or_field = None
            matched_val = None

            # Check A: Match against cited SQL row cells
            if row_citations:
                for row_id in row_citations:
                    try:
                        row_cells = evidence_store.get_row(row_id)
                    except KeyError:
                        continue

                    for col_name, cell_val in row_cells.items():
                        cell_float = _parse_float(cell_val)
                        if cell_float is None:
                            continue

                        diff = abs(claimed_float - cell_float)
                        rel_diff = diff / max(abs(cell_float), 1.0)

                        # Match criteria: exact match, within 2% rounding, or lower-bound statement (e.g. "over $50,000")
                        is_exact_or_round = (diff <= 0.05 or rel_diff <= 0.02)
                        is_bound_match = (has_lower_bound and cell_float >= claimed_float and (cell_float - claimed_float) / cell_float < 0.20)

                        if is_exact_or_round or is_bound_match:
                            matched = True
                            matched_id = row_id
                            matched_col_or_field = col_name
                            matched_val = cell_val
                            break

                    if matched:
                        break

            # Check B: Match against cited Document Chunks
            if not matched and doc_citations:
                for doc_id in doc_citations:
                    chunk = evidence_store.get_chunk(doc_id)
                    if chunk and raw_matched_num in chunk.text:
                        matched = True
                        matched_id = doc_id
                        matched_col_or_field = "document_text"
                        matched_val = raw_matched_num
                        break

            if matched:
                report.numeric_checks.append(
                    NumericCheck(
                        raw_text=match.group(0).strip(),
                        claimed_value=claimed_float,
                        sentence=segment,
                        status="VERIFIED",
                        row_id=matched_id,
                        matched_column=matched_col_or_field,
                        cell_value=matched_val,
                        message=f"Claimed {match.group(0).strip()} verified against [{matched_id}] ({matched_col_or_field} = {matched_val})",
                    )
                )
                report.verified_numbers_count += 1

            elif row_citations or doc_citations:
                # Segment had citations, but number could not be reconciled
                cited_sources = row_citations + doc_citations
                msg = f"Discrepancy: claimed {match.group(0).strip()} does not match data in cited sources {cited_sources}."
                report.numeric_checks.append(
                    NumericCheck(
                        raw_text=match.group(0).strip(),
                        claimed_value=claimed_float,
                        sentence=segment,
                        status="DISCREPANCY",
                        row_id=cited_sources[0],
                        message=msg,
                    )
                )
                report.discrepancy_count += 1
                report.is_clean = False

            else:
                # Disregard small integers 0-5 used as descriptive words ("top 3 products")
                if claimed_float.is_integer() and int(claimed_float) <= 5:
                    continue

                msg = f"Unsupported claim: number {match.group(0).strip()} stated without an evidence citation tag."
                report.numeric_checks.append(
                    NumericCheck(
                        raw_text=match.group(0).strip(),
                        claimed_value=claimed_float,
                        sentence=segment,
                        status="UNSUPPORTED",
                        message=msg,
                    )
                )
                report.unsupported_claims_count += 1
                report.is_clean = False

    return report
