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
    causal_warnings: list[str] = field(default_factory=list)
    valid_count: int = 0
    invalid_count: int = 0
    verified_numbers_count: int = 0
    discrepancy_count: int = 0
    unsupported_claims_count: int = 0
    is_clean: bool = True
    is_truncated: bool = False

    def get_invalid_ids(self) -> list[str]:
        return [c.target_id for c in self.citations if not c.is_valid]

    def get_discrepancies(self) -> list[str]:
        return [nc.message for nc in self.numeric_checks if nc.status == "DISCREPANCY"]

    def get_unsupported_claims(self) -> list[str]:
        return [nc.message for nc in self.numeric_checks if nc.status == "UNSUPPORTED"]


CITATION_PATTERN = re.compile(r"\[\[(Q\d+:R\d+|D:[a-zA-Z0-9_\-]+:[a-zA-Z0-9_\-]+)\]\]")
LOOSE_CITATION_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")

CAUSAL_PHRASES = (
    "caused the", "caused a", "caused our", "causing the",
    "directly caused", "led directly to", "responsible for the decline",
    "responsible for the drop", "responsible for the loss",
    "was the cause of", "were the cause of", "the root cause of the decline",
    "the reason for the drop in revenue",
)

# Direction words for reconciling variance and trends
DECLINE_WORDS = (
    "decline", "declined", "declining", "declines",
    "drop", "dropped", "dropping", "drops",
    "decrease", "decreased", "decreasing", "decreases",
    "fell", "fall", "falling", "falls",
    "loss", "lost", "down", "reduced", "reduction"
)
INCREASE_WORDS = (
    "increase", "increased", "increasing", "increases",
    "grew", "grow", "growing", "growth",
    "gain", "gained", "gaining", "gains",
    "rose", "rise", "rising", "rises",
    "higher", "improved", "improvement", "positive change"
)

# Matches currency numbers, decimals, integers with optional signs: e.g. -$2,611.99, R$738,876.88, £22.20, 53,803.23, -54.41, 6, 42.5%
NUMERIC_PATTERN = re.compile(
    r"([-–—]?)(?:(?:R\$|[\$£€])\s*)?([-–—]?)((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?:%|percent)?"
)


def _parse_float(val: Any) -> float | None:
    """Safely convert cell value or string to float."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, decimal.Decimal):
        return float(val)
    clean_str = str(val).replace(",", "").replace("R$", "").replace("$", "").replace("£", "").replace("€", "").strip()
    try:
        return float(clean_str)
    except (ValueError, TypeError):
        return None


def _is_calendar_or_bullet(raw_num_str: str, sentence: str, match_start: int) -> bool:
    """Detect if number is a bullet point, year, quarter, HTTP status code, day of month, duration, or version."""
    # Check if number is an isolated year (1900 - 2099)
    if re.fullmatch(r"\d{4}", raw_num_str):
        num_val = int(raw_num_str)
        if 1900 <= num_val <= 2099:
            return True

    # Check if number is an HTTP error/status code: 400-599 (e.g. 504, 503, 500, 502, 404, etc.)
    if re.fullmatch(r"[45]\d{2}", raw_num_str):
        return True

    # Check if number is part of a quarter designation: 'Q1', 'Q2', 'Q3', 'Q4'
    if match_start > 0 and sentence[match_start - 1] in ('Q', 'q'):
        return True
    if match_start >= 8 and sentence[max(0, match_start - 8):match_start].lower().endswith("quarter "):
        return True

    # Check if number is part of a software version string: 'v2.4', 'v1.0', 'version 2.4'
    if match_start > 0 and sentence[match_start - 1] in ('v', 'V'):
        return True
    if match_start >= 8 and sentence[max(0, match_start - 8):match_start].lower().endswith("version "):
        return True

    # Check surrounding window (30 chars before and after)
    window_wide = sentence[max(0, match_start - 30):min(len(sentence), match_start + len(raw_num_str) + 30)].lower()

    if any(k in window_wide for k in ("error", "status", "timeout", "gateway", "code", "http", "version")):
        if re.fullmatch(r"\d{3,4}", raw_num_str):
            return True

    # Check if number is a day of month (e.g. 'March 12', '12 March', 'March 12th', 'on the 12th')
    month_names = (
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
        "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"
    )
    if re.fullmatch(r"\d{1,2}(?:st|nd|rd|th)?", raw_num_str):
        clean_digits = re.sub(r"\D", "", raw_num_str)
        if clean_digits:
            val = int(clean_digits)
            if 1 <= val <= 31:
                if any(re.search(r"\b" + m + r"\b", window_wide) for m in month_names):
                    return True
                if "date" in window_wide or "day" in window_wide:
                    return True

    # Check if number is a time duration or clock time (e.g. '4 hours', '8 hrs', '30 minutes', '2 days')
    if re.search(r"\b" + re.escape(raw_num_str) + r"\s*(?:hours?|hrs?|minutes?|mins?|seconds?|secs?|days?|weeks?|months?|am|pm)\b", sentence, re.I):
        return True
    if re.search(r"\b(?:for|in|within|every)\s+" + re.escape(raw_num_str) + r"\s*(?:hours?|hrs?|minutes?|mins?|seconds?|secs?|days?|weeks?|months?)\b", sentence, re.I):
        return True

    # Check if number is a ticket ID or query/row label: 'TK-1002', 'ID-12', 'BUG-404'
    prefix_chars = sentence[max(0, match_start - 4):match_start].upper()
    if any(prefix_chars.endswith(p) for p in ("TK-", "ID-", "BUG-", "TK", "ID", "BUG")):
        return True

    # Check if number is a list bullet: '1. ', '2. ', '3) ' at line or segment start
    prefix = sentence[:match_start].strip()
    if prefix in ("", "*", "-", "•") and (match_start + len(raw_num_str) < len(sentence)):
        next_char = sentence[match_start + len(raw_num_str)]
        if next_char in (".", ")", ":", "-"):
            return True

    return False


METRIC_KEYWORDS = (
    "order", "orders", "unit", "units", "ticket", "tickets",
    "product", "products", "customer", "customers", "complaint", "complaints",
    "item", "items", "case", "cases", "count", "total", "sum",
    "quantity", "qty", "avg", "average", "rate", "percentage", "margin",
    "line", "lines", "transaction", "transactions",
)


def _is_real_metric(raw_full: str, raw_num_str: str, sentence: str, match_start: int) -> bool:
    """Determine if a number is a genuine business/financial metric rather than an incidental number."""
    # 1. Any currency symbol makes it a metric ($100, £20, €50)
    if any(sym in raw_full for sym in ("$", "£", "€")):
        return True

    # 2. Percentage makes it a metric (15%, 4.5%)
    if "%" in raw_full or "percent" in raw_full.lower():
        return True

    # 3. Decimals indicate continuous measured metrics (53.80, 4.50, 0.25)
    if "." in raw_num_str:
        return True

    # 4. Comma-formatted numbers indicate large measured quantities (1,450, 50,000)
    if "," in raw_full:
        return True

    # 5. Table rows indicate structured metric columns (| SecureVault | 412 |)
    trimmed = sentence.strip()
    if trimmed.startswith("|") and trimmed.endswith("|"):
        return True

    # 6. Check if number is inside bold name/title or before colon (e.g. '**REGENCY CAKESTAND 3 TIER**:')
    colon_idx = sentence.find(":")
    if colon_idx != -1 and match_start < colon_idx:
        return False

    # 7. Check if number is an apostrophe decades/style descriptor (e.g. 50's, 80s)
    match_end = match_start + len(raw_num_str)
    if match_end < len(sentence) and sentence[match_end:match_end+2].lower() in ("'s", "s ", "s,"):
        return False

    # 8. For bare unformatted integers, require adjacent metric/count context
    window = sentence[max(0, match_start - 35):min(len(sentence), match_start + len(raw_num_str) + 35)].lower()
    if any(re.search(r"\b" + kw + r"\b", window) for kw in METRIC_KEYWORDS):
        return True

    return False


def verify_citations(
    text: str,
    evidence_store: EvidenceStore,
    semantic_model: Any = None,
) -> CitationReport:
    """Extract and verify all citations and perform deterministic numeric, currency, and date reconciliation."""
    report = CitationReport()
    seen_citation_ids: set[str] = set()

    expected_currency = getattr(semantic_model, "default_currency", "USD") if semantic_model else "USD"
    expected_symbol = getattr(semantic_model, "currency_symbol", "$") if semantic_model else "$"

    # 1. Provenance Verification
    # Detect malformed nested triple brackets like [[[Q1:R1]]]
    if "[[[" in text or "]]]" in text:
        report.citations.append(
            Citation(
                raw="[[[...]]]",
                target_id="nested_brackets",
                is_valid=False,
                evidence_type="unknown",
                error="Malformed nested citation syntax: redundant triple brackets [[[...]]].",
            )
        )
        report.invalid_count += 1
        report.is_clean = False

    # Detect malformed grouped brackets like [[Q1:R1], [Q1:R2]] or [[Q1:R1, Q1:R2]] or [[... through ...]]
    grouped_bracket_matches = re.finditer(r"\[\[(.*?)\]\]", text)
    for g_match in grouped_bracket_matches:
        inner = g_match.group(1).strip()
        # If inner contains commas, brackets, or range keywords, it is malformed
        if any(bad in inner for bad in (",", "]", "[", " through ", " to ", "..", " - ")):
            report.citations.append(
                Citation(
                    raw=g_match.group(0),
                    target_id=inner,
                    is_valid=False,
                    evidence_type="unknown",
                    error=f"Malformed grouped citation '{g_match.group(0)}'. Citations must be individually enclosed as [[Q1:R1]] [[Q1:R2]].",
                )
            )
            report.invalid_count += 1
            report.is_clean = False

    # Detect single-bracket citation tags like [Q1:R1] that forgot double-brackets
    single_bracket_matches = re.finditer(r"(?<!\[)\[(Q\d+:R\d+|D:[a-zA-Z0-9_\-]+:[a-zA-Z0-9_\-]+)\](?!\])", text)
    for s_match in single_bracket_matches:
        report.citations.append(
            Citation(
                raw=s_match.group(0),
                target_id=s_match.group(1),
                is_valid=False,
                evidence_type="unknown",
                error=f"Malformed single-bracket citation '{s_match.group(0)}'. Citations must use double brackets [[...]].",
            )
        )
        report.invalid_count += 1
        report.is_clean = False

    # Extract clean individual bracket tokens
    all_bracket_tokens = LOOSE_CITATION_PATTERN.findall(text)
    for raw_token in all_bracket_tokens:
        token = raw_token.strip()
        if token in seen_citation_ids:
            continue
        seen_citation_ids.add(token)

        raw_str = f"[[{token}]]"

        # Check strict syntax
        if not CITATION_PATTERN.fullmatch(raw_str):
            # Already handled if it was caught by grouped brackets, otherwise flag
            if not any(token in c.target_id for c in report.citations if not c.is_valid):
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
    all_valid_sql_citations = [c.target_id for c in report.citations if c.is_valid and c.target_id.startswith("Q")]

    # Break text into sentence/line segments
    segments = [s.strip() for s in re.split(r"[\n\r]+|\.\s+", text) if s.strip()]

    for segment in segments:
        # Check date semantic accuracy: order_month represents the start of the month, not period ending
        MONTH_PATTERN = r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        date_ending_match = re.search(
            r"\b(?:period ending|period ended|ended|ending)\s+(?:\d{4}-\d{2}(?:-\d{2})?|" + MONTH_PATTERN + r"(?:\s+\d{4})?)\b",
            segment,
            re.IGNORECASE,
        )
        if date_ending_match:
            claimed_str = date_ending_match.group(0)
            msg = (
                f"Date semantic discrepancy: '{claimed_str}' is invalid; "
                f"order_month represents the start of the monthly period (use 'for the month of ...' or 'month starting ...')."
            )
            report.numeric_checks.append(
                NumericCheck(
                    raw_text=claimed_str,
                    claimed_value=0.0,
                    sentence=segment,
                    status="DISCREPANCY",
                    message=msg,
                )
            )
            report.discrepancy_count += 1
            report.is_clean = False

        # Find citations in this segment
        all_segment_citations = [
            c_id for c_id in CITATION_PATTERN.findall(segment)
            if evidence_store.has_id(c_id)
        ]
        row_citations = [c for c in all_segment_citations if c.startswith("Q")]
        doc_citations = [c for c in all_segment_citations if c.startswith("D")]

        # Check causal wording lint for document / ticket claims (spec section 8.7)
        if doc_citations or any(kw in segment.lower() for kw in ("ticket", "complaint", "feedback", "customer report")):
            seg_lower = segment.lower()
            for phrase in CAUSAL_PHRASES:
                if phrase in seg_lower:
                    warning = (
                        f"Causal lint: '{phrase}' in document claim. Customer feedback and tickets "
                        f"describe reported user sentiment, not mathematically proven direct revenue causation."
                    )
                    if warning not in report.causal_warnings:
                        report.causal_warnings.append(warning)

        # Strip citations and full dates (YYYY-MM-DD) before looking for claimed numbers
        cleaned_segment = LOOSE_CITATION_PATTERN.sub("", segment)
        cleaned_segment = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", cleaned_segment)
        cleaned_segment = re.sub(r"\b\d{4}-\d{2}\b", "", cleaned_segment)

        # Detect inequality / approximation modifiers in segment
        has_lower_bound = bool(re.search(r"\b(?:over|more than|exceeding|above|\+)\b", segment, re.I))

        for match in NUMERIC_PATTERN.finditer(cleaned_segment):
            raw_full = match.group(0).strip()
            raw_sign = "-" if ("-" in match.group(1) or "-" in match.group(2) or "–" in match.group(1) or "—" in match.group(1)) else ""
            raw_matched_num = match.group(3).replace(",", "")
            claimed_float = _parse_float(raw_sign + raw_matched_num)
            if claimed_float is None:
                continue

            # Check currency symbol mismatch
            claimed_symbol = None
            if raw_full.startswith("R$") or "brl" in segment.lower() or "real" in segment.lower() or "reais" in segment.lower():
                claimed_symbol = "R$"
            elif raw_full.startswith("$") or "dollar" in segment.lower() or "usd" in segment.lower():
                claimed_symbol = "$"
            elif raw_full.startswith("£") or "pound" in segment.lower() or "gbp" in segment.lower():
                claimed_symbol = "£"
            elif raw_full.startswith("€") or "euro" in segment.lower() or "eur" in segment.lower():
                claimed_symbol = "€"

            if claimed_symbol:
                if claimed_symbol != expected_symbol:
                    msg = (
                        f"Currency unit mismatch: claimed '{claimed_symbol}' ({raw_full}) "
                        f"but declared semantic model currency is '{expected_symbol}' ({expected_currency})."
                    )
                    report.numeric_checks.append(
                        NumericCheck(
                            raw_text=raw_full,
                            claimed_value=claimed_float,
                            sentence=segment,
                            status="DISCREPANCY",
                            message=msg,
                        )
                    )
                    report.discrepancy_count += 1
                    report.is_clean = False
                    continue

            # Skip calendar years or list bullets
            if _is_calendar_or_bullet(raw_matched_num, cleaned_segment, match.start()):
                continue

            # Verify only real metrics (exclude dates, times, error codes, and incidental numbers)
            if not _is_real_metric(raw_full, raw_matched_num, cleaned_segment, match.start()):
                continue

            matched = False
            matched_id = None
            matched_col_or_field = None
            matched_val = None

            # Check A: Match against cited SQL row cells
            candidate_rows = row_citations if row_citations else all_valid_sql_citations
            if candidate_rows:
                for row_id in candidate_rows:
                    try:
                        row_cells = evidence_store.get_row(row_id)
                    except KeyError:
                        continue

                    for col_name, cell_val in row_cells.items():
                        cell_float = _parse_float(cell_val)
                        if cell_float is None:
                            continue

                        diff_signed = abs(claimed_float - cell_float)
                        diff_abs = abs(abs(claimed_float) - abs(cell_float))
                        rel_diff_signed = diff_signed / max(abs(cell_float), 1.0)
                        rel_diff_abs = diff_abs / max(abs(cell_float), 1.0)

                        has_approx = bool(re.search(r"\b(?:approximately|approx|about|around|~)\b", segment, re.I))
                        if has_approx:
                            is_exact_or_round = (
                                diff_signed <= 0.05 or rel_diff_signed <= 0.02
                                or diff_abs <= 0.05 or rel_diff_abs <= 0.02
                            )
                        else:
                            is_exact_or_round = (diff_signed <= 0.05 or diff_abs <= 0.05)

                        is_bound_match = (has_lower_bound and cell_float >= claimed_float and (cell_float - claimed_float) / max(cell_float, 1.0) < 0.20)

                        if is_exact_or_round or is_bound_match:
                            matched = True
                            matched_id = row_id
                            matched_col_or_field = col_name
                            matched_val = cell_val
                            break

                    if matched:
                        break

            # Check B: Match against cited Document Chunks
            # Only true business/financial metrics (currency, percentages, decimals) are verified against documents.
            # Plain numbers from text tickets (error codes, dates, durations, IDs) must NOT inflate verified metrics count.
            has_metric_sign = bool(raw_full.startswith(("$", "£", "€")) or "%" in raw_full or "percent" in segment.lower() or "." in raw_matched_num)
            if not matched and doc_citations and has_metric_sign:
                for doc_id in doc_citations:
                    chunk = evidence_store.get_chunk(doc_id)
                    if chunk and raw_matched_num in chunk.text:
                        matched = True
                        matched_id = doc_id
                        matched_col_or_field = "document_text"
                        matched_val = raw_matched_num
                        break

            # Check C: Match derived metrics (sum, difference, percent change, share, count) from cited SQL rows
            if not matched and candidate_rows:
                col_sums: dict[str, float] = {}
                col_counts: dict[str, int] = {}
                numeric_cells_list: list[tuple[str, str, float]] = []

                for r_id in candidate_rows:
                    try:
                        r_cells = evidence_store.get_row(r_id)
                    except KeyError:
                        continue
                    for c_name, c_val in r_cells.items():
                        c_num = _parse_float(c_val)
                        if c_num is not None:
                            col_sums[c_name] = col_sums.get(c_name, 0.0) + c_num
                            col_counts[c_name] = col_counts.get(c_name, 0) + 1
                            numeric_cells_list.append((r_id, c_name, c_num))

                # Check column sums across cited rows
                for c_name, total_sum in col_sums.items():
                    if col_counts[c_name] >= 2:
                        diff = abs(claimed_float - total_sum)
                        rel_diff = diff / max(abs(total_sum), 1.0)
                        if diff <= 0.05 or rel_diff <= 0.02:
                            matched = True
                            matched_id = candidate_rows[0]
                            matched_col_or_field = f"derived_sum({c_name})"
                            matched_val = round(total_sum, 2)
                            break

                # Check pairwise differences and percent changes across cited values
                if not matched and len(numeric_cells_list) >= 2:
                    for i in range(len(numeric_cells_list)):
                        for j in range(len(numeric_cells_list)):
                            if i == j:
                                continue
                            r1, c1, v1 = numeric_cells_list[i]
                            r2, c2, v2 = numeric_cells_list[j]

                            # Difference
                            diff_val = v1 - v2
                            abs_diff = abs(diff_val)
                            if abs(claimed_float - diff_val) <= 0.05 or abs(claimed_float - abs_diff) <= 0.05:
                                matched = True
                                matched_id = r1
                                matched_col_or_field = f"derived_diff({c1}, {c2})"
                                matched_val = round(diff_val, 2)
                                break

                            # Percent change: ((v1 - v2) / abs(v2)) * 100
                            if abs(v2) > 0.001:
                                pct_change = ((v1 - v2) / abs(v2)) * 100.0
                                abs_pct = abs(pct_change)
                                pct_share = (v1 / v2) * 100.0
                                if (
                                    abs(claimed_float - pct_change) <= 0.1
                                    or abs(claimed_float - abs_pct) <= 0.1
                                    or abs(claimed_float - pct_share) <= 0.1
                                ):
                                    matched = True
                                    matched_id = r1
                                    matched_col_or_field = f"derived_pct({c1}, {c2})"
                                    matched_val = round(pct_change if abs(claimed_float - pct_change) <= 0.1 else pct_share, 2)
                                    break
                        if matched:
                            break

                # Check row count
                if not matched and len(candidate_rows) >= 2:
                    if abs(claimed_float - len(candidate_rows)) < 0.01:
                        matched = True
                        matched_id = candidate_rows[0]
                        matched_col_or_field = "derived_count(rows)"
                        matched_val = len(candidate_rows)

            if matched:
                direction_discrepancy = None
                if matched_id and matched_id.startswith("Q") and matched_col_or_field:
                    col_lower = matched_col_or_field.lower()

                    # Check unit mismatch: percentage claimed on currency/count, or currency claimed on count/rate
                    is_pct_claimed = "%" in raw_full or "percent" in segment.lower()
                    is_currency_claimed = any(s in raw_full for s in ("$", "£", "€"))
                    is_currency_col = any(k in col_lower for k in ("amount", "revenue", "sales", "price", "decline", "spend", "cost", "total_revenue"))
                    is_pct_col = any(k in col_lower for k in ("pct", "percent", "percentage", "rate", "share", "ratio"))
                    is_count_col = any(k in col_lower for k in ("count", "orders", "tickets", "units", "quantity", "qty", "total_orders", "customer_count"))

                    if is_pct_claimed and (is_currency_col or is_count_col) and not is_pct_col:
                        report.numeric_checks.append(
                            NumericCheck(
                                raw_text=raw_full,
                                claimed_value=claimed_float,
                                sentence=segment,
                                status="DISCREPANCY",
                                row_id=matched_id,
                                matched_column=matched_col_or_field,
                                cell_value=matched_val,
                                message=f"Unit mismatch: Claimed '{raw_full}' as percentage, but {matched_col_or_field} is a non-percentage column.",
                            )
                        )
                        report.discrepancy_count += 1
                        report.is_clean = False
                        continue

                    if is_currency_claimed and (is_count_col or is_pct_col) and not is_currency_col:
                        report.numeric_checks.append(
                            NumericCheck(
                                raw_text=raw_full,
                                claimed_value=claimed_float,
                                sentence=segment,
                                status="DISCREPANCY",
                                row_id=matched_id,
                                matched_column=matched_col_or_field,
                                cell_value=matched_val,
                                message=f"Unit mismatch: Claimed '{raw_full}' with currency symbol, but {matched_col_or_field} is a count/ratio column.",
                            )
                        )
                        report.discrepancy_count += 1
                        report.is_clean = False
                        continue

                    row_cells = evidence_store.get_row(matched_id)
                    cell_float = _parse_float(matched_val)

                    is_decline_col = "decline" in col_lower or "drop" in col_lower
                    is_change_col = "change" in col_lower or "growth" in col_lower or "diff" in col_lower or "delta" in col_lower

                    prev_val = None
                    curr_val = None
                    for k, v in row_cells.items():
                        kl = k.lower()
                        if "prev" in kl:
                            prev_val = _parse_float(v)
                        elif "monthly_sales" in kl or "current" in kl or (kl == "amount" and is_decline_col):
                            curr_val = _parse_float(v)

                    data_reality = None
                    if prev_val is not None and curr_val is not None:
                        if curr_val > prev_val + 0.05:
                            data_reality = "INCREASE"
                        elif curr_val < prev_val - 0.05:
                            data_reality = "DECLINE"
                    elif is_decline_col and cell_float is not None:
                        if cell_float > 0.05:
                            data_reality = "DECLINE"
                        elif cell_float < -0.05:
                            data_reality = "INCREASE"
                    elif is_change_col and cell_float is not None:
                        if cell_float > 0.05:
                            data_reality = "INCREASE"
                        elif cell_float < -0.05:
                            data_reality = "DECLINE"

                    if data_reality:
                        seg_lower = segment.lower()
                        claims_decline = any(re.search(r"\b" + w + r"\b", seg_lower) for w in DECLINE_WORDS)
                        claims_increase = any(re.search(r"\b" + w + r"\b", seg_lower) for w in INCREASE_WORDS)

                        if claims_increase and claims_decline:
                            if re.search(r"\b(?:revenue increase|growth|positive change|grew)\b", seg_lower):
                                claimed_dir = "INCREASE"
                            else:
                                claimed_dir = "DECLINE"
                        elif claims_decline:
                            claimed_dir = "DECLINE"
                        elif claims_increase:
                            claimed_dir = "INCREASE"
                        else:
                            claimed_dir = None

                        if claimed_dir and claimed_dir != data_reality:
                            direction_discrepancy = (
                                f"Direction discrepancy: Claimed {claimed_dir.lower()} of {match.group(0).strip()}, "
                                f"but data indicates {data_reality.lower()} "
                                f"({matched_col_or_field} = {matched_val})."
                            )

                if direction_discrepancy:
                    report.numeric_checks.append(
                        NumericCheck(
                            raw_text=match.group(0).strip(),
                            claimed_value=claimed_float,
                            sentence=segment,
                            status="DISCREPANCY",
                            row_id=matched_id,
                            matched_column=matched_col_or_field,
                            cell_value=matched_val,
                            message=direction_discrepancy,
                        )
                    )
                    report.discrepancy_count += 1
                    report.is_clean = False
                else:
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
