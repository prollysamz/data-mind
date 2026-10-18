"""Deterministic Verifier Mutation and False-Positive Testing Harness.

Tests the verifier against at least 50 automated mutations across multiple
failure classes (perturbation, magnitude, direction flip, currency swap,
citation swap, invalid ID, missing citation, date semantic, unit mismatch,
malformed citation) and evaluates false-positive rates on clean non-metric text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from datamind.adapters.base import QueryResult
from datamind.agent.evidence import EvidenceStore
from datamind.agent.verifier import verify_citations
from datamind.retrieval.base import Chunk


@dataclass
class MutationCase:
    name: str
    category: str
    original_text: str
    mutated_text: str
    evidence_store: EvidenceStore
    expected_caught: bool = True
    caught: bool = False
    details: str = ""


@dataclass
class MutationResult:
    total_mutations: int
    caught_count: int
    missed_count: int
    catch_rate_pct: float
    by_category: dict[str, dict[str, Any]]
    misses: list[dict[str, Any]] = field(default_factory=list)


def create_seed_evidence_store() -> EvidenceStore:
    """Create a populated EvidenceStore with realistic queries and documents."""
    store = EvidenceStore()

    # Query 1: MoM Revenue Declines
    q1_result = QueryResult(
        columns=["product_name", "order_month", "amount", "mom_revenue_decline"],
        rows=[
            ("Novaship", "2026-03-01", 28357.22, 53803.23),
            ("CloudSync", "2026-03-01", 12450.00, 3482.85),
            ("DataFlow", "2026-03-01", 45200.50, -6812.40),
            ("SecureVault", "2026-03-01", 68100.00, 5686.56),
            ("OmniChat", "2026-03-01", 19200.10, -1200.00),
        ],
        query_id="qid-mom-declines",
        elapsed_ms=8.5,
        truncated=False,
    )
    store.add_query(
        "SELECT product_name, order_month, amount, mom_revenue_decline FROM SALES",
        "Month-over-month revenue changes",
        q1_result,
    )

    # Query 2: Product Totals and Customer Counts
    q2_result = QueryResult(
        columns=["product_name", "total_orders", "customer_count", "total_revenue"],
        rows=[
            ("Novaship", 142, 85, 28357.22),
            ("SecureVault", 310, 190, 68100.00),
            ("DataFlow", 205, 115, 45200.50),
        ],
        query_id="qid-product-totals",
        elapsed_ms=6.2,
        truncated=False,
    )
    store.add_query(
        "SELECT product_name, total_orders, customer_count, total_revenue FROM PRODUCTS",
        "Product aggregate orders and customer counts",
        q2_result,
    )

    # Query 3: Ticket counts by priority
    q3_result = QueryResult(
        columns=["priority", "ticket_count"],
        rows=[
            ("Critical", 4),
            ("High", 18),
            ("Medium", 42),
            ("Low", 110),
        ],
        query_id="qid-ticket-counts",
        elapsed_ms=4.1,
        truncated=False,
    )
    store.add_query(
        "SELECT priority, COUNT(*) FROM TICKETS GROUP BY priority",
        "Support tickets by priority",
        q3_result,
    )

    # Document Chunks
    store.add_chunks(
        "gateway timeout duplicate charges",
        [
            Chunk(
                chunk_id="D:tickets:TK-1002",
                doc_name="tickets",
                text="Customer experienced 504 gateway timeout on billing portal for Novaship. Repeated attempts caused duplicate transactions of $120.00.",
                metadata={"ticket_id": "TK-1002", "product": "Novaship"},
            ),
            Chunk(
                chunk_id="D:tickets:TK-1005",
                doc_name="tickets",
                text="High latency and connection reset on API sync during v2.4 upgrade on March 12th.",
                metadata={"ticket_id": "TK-1005", "product": "DataFlow"},
            ),
        ],
    )

    return store


def build_mutation_suite() -> list[MutationCase]:
    """Build at least 50 varied mutation cases across all failure classes."""
    store = create_seed_evidence_store()
    cases: list[MutationCase] = []

    # Category 1: Value Perturbation (slight change in numbers)
    perturbations = [
        ("Novaship decline", "Novaship experienced a decline of $53,803.23 [[Q1:R1]].", "Novaship experienced a decline of $53,804.23 [[Q1:R1]]."),
        ("CloudSync decline", "CloudSync declined by $3,482.85 [[Q1:R2]].", "CloudSync declined by $3,480.00 [[Q1:R2]]."),
        ("Novaship revenue", "Novaship March revenue was $28,357.22 [[Q1:R1]].", "Novaship March revenue was $28,356.00 [[Q1:R1]]."),
        ("Critical tickets", "There were 4 critical tickets reported [[Q3:R1]].", "There were 5 critical tickets reported [[Q3:R1]]."),
        ("High tickets", "There were 18 high priority tickets [[Q3:R2]].", "There were 19 high priority tickets [[Q3:R2]]."),
        ("Customer count", "SecureVault served 190 customers [[Q2:R2]].", "SecureVault served 195 customers [[Q2:R2]]."),
    ]
    for name, orig, mut in perturbations:
        cases.append(MutationCase(f"perturbation_{name}", "value_perturbation", orig, mut, store))

    # Category 2: Magnitude Changes (10x larger or 10x smaller)
    magnitudes = [
        ("Novaship 10x", "Novaship experienced a decline of $53,803.23 [[Q1:R1]].", "Novaship experienced a decline of $538,032.30 [[Q1:R1]]."),
        ("Novaship 0.1x", "Novaship experienced a decline of $53,803.23 [[Q1:R1]].", "Novaship experienced a decline of $5,380.32 [[Q1:R1]]."),
        ("Orders 10x", "Novaship had 142 total orders [[Q2:R1]].", "Novaship had 1,420 total orders [[Q2:R1]]."),
        ("Tickets 10x", "There were 4 critical tickets [[Q3:R1]].", "There were 40 critical tickets [[Q3:R1]]."),
        ("SecureVault 100x", "SecureVault generated $68,100.00 [[Q1:R4]].", "SecureVault generated $681,000.00 [[Q1:R4]]."),
    ]
    for name, orig, mut in magnitudes:
        cases.append(MutationCase(f"magnitude_{name}", "magnitude_change", orig, mut, store))

    # Category 3: Direction Word Flips (decline -> increase, drop -> growth)
    direction_flips = [
        ("Novaship decline to growth", "Novaship had a revenue decline of $53,803.23 [[Q1:R1]].", "Novaship had a revenue growth of $53,803.23 [[Q1:R1]]."),
        ("CloudSync drop to increase", "CloudSync dropped by $3,482.85 in revenue [[Q1:R2]].", "CloudSync increased by $3,482.85 in revenue [[Q1:R2]]."),
        ("DataFlow increase to fell", "DataFlow grew by $6,812.40 [[Q1:R3]].", "DataFlow fell by $6,812.40 [[Q1:R3]]."),
        ("SecureVault decline to improved", "SecureVault declined by $5,686.56 [[Q1:R4]].", "SecureVault improved by $5,686.56 [[Q1:R4]]."),
        ("OmniChat gain to decline", "OmniChat gained $1,200.00 in sales [[Q1:R5]].", "OmniChat suffered a decline of $1,200.00 in sales [[Q1:R5]]."),
        ("Novaship drop to rose", "Novaship sales dropped by $53,803.23 [[Q1:R1]].", "Novaship sales rose by $53,803.23 [[Q1:R1]]."),
    ]
    for name, orig, mut in direction_flips:
        cases.append(MutationCase(f"direction_{name}", "direction_flip", orig, mut, store))

    # Category 4: Currency Symbol Swaps ($ -> € or £)
    currency_swaps = [
        ("Dollar to Euro Novaship", "Novaship revenue was $28,357.22 [[Q1:R1]].", "Novaship revenue was €28,357.22 [[Q1:R1]]."),
        ("Dollar to Pound SecureVault", "SecureVault revenue was $68,100.00 [[Q1:R4]].", "SecureVault revenue was £68,100.00 [[Q1:R4]]."),
        ("Dollar to Euro Decline", "Revenue declined by $53,803.23 [[Q1:R1]].", "Revenue declined by €53,803.23 [[Q1:R1]]."),
        ("Dollar to Pound CloudSync", "CloudSync sales were $12,450.00 [[Q1:R2]].", "CloudSync sales were £12,450.00 [[Q1:R2]]."),
        ("Document ticket dollar to euro", "Customer had duplicate charges of $120.00 [[D:tickets:TK-1002]].", "Customer had duplicate charges of €120.00 [[D:tickets:TK-1002]]."),
    ]
    for name, orig, mut in currency_swaps:
        cases.append(MutationCase(f"currency_{name}", "currency_swap", orig, mut, store))

    # Category 5: Citation Row Swaps (citing wrong row)
    citation_swaps = [
        ("Novaship citing CloudSync", "Novaship revenue was $28,357.22 [[Q1:R1]].", "Novaship revenue was $28,357.22 [[Q1:R2]]."),
        ("CloudSync citing SecureVault", "CloudSync revenue was $12,450.00 [[Q1:R2]].", "CloudSync revenue was $12,450.00 [[Q1:R4]]."),
        ("Critical tickets citing Low", "Critical tickets count was 4 [[Q3:R1]].", "Critical tickets count was 4 [[Q3:R4]]."),
        ("Customer count citing DataFlow", "SecureVault had 190 customers [[Q2:R2]].", "SecureVault had 190 customers [[Q2:R3]]."),
        ("Novaship decline citing DataFlow", "Novaship declined by $53,803.23 [[Q1:R1]].", "Novaship declined by $53,803.23 [[Q1:R3]]."),
    ]
    for name, orig, mut in citation_swaps:
        cases.append(MutationCase(f"citation_swap_{name}", "citation_swap", orig, mut, store))

    # Category 6: Invalid Citation IDs (fabricated IDs)
    invalid_ids = [
        ("Nonexistent row Q1:R99", "Novaship revenue was $28,357.22 [[Q1:R1]].", "Novaship revenue was $28,357.22 [[Q1:R99]]."),
        ("Nonexistent query Q9:R1", "Critical tickets count was 4 [[Q3:R1]].", "Critical tickets count was 4 [[Q9:R1]]."),
        ("Nonexistent doc D:tickets:TK-9999", "Timeout on portal [[D:tickets:TK-1002]].", "Timeout on portal [[D:tickets:TK-9999]]."),
        ("Fabricated Q2:R50", "SecureVault served 190 customers [[Q2:R2]].", "SecureVault served 190 customers [[Q2:R50]]."),
        ("Nonexistent doc D:unknown:0", "Duplicate charges reported [[D:tickets:TK-1002]].", "Duplicate charges reported [[D:unknown:0]]."),
    ]
    for name, orig, mut in invalid_ids:
        cases.append(MutationCase(f"invalid_id_{name}", "invalid_citation_id", orig, mut, store))

    # Category 7: Deleted Citations (bare numbers without citation tags)
    deleted_citations = [
        ("Novaship decline uncited", "Novaship declined by $53,803.23 [[Q1:R1]].", "Novaship declined by $53,803.23."),
        ("CloudSync sales uncited", "CloudSync sales reached $12,450.00 [[Q1:R2]].", "CloudSync sales reached $12,450.00."),
        ("Customer count uncited", "Total customers was 190 [[Q2:R2]].", "Total customers was 190."),
        ("Orders count uncited", "Customer completed 142 orders [[Q2:R1]].", "Customer completed 142 orders."),
        ("Critical tickets uncited", "A total of 18 tickets were logged [[Q3:R2]].", "A total of 18 tickets were logged."),
    ]
    for name, orig, mut in deleted_citations:
        cases.append(MutationCase(f"deleted_cit_{name}", "deleted_citation", orig, mut, store))

    # Category 8: Date Semantic Misrepresentations ("period ending" vs month start)
    date_semantics = [
        ("Period ending 2026-03-01", "For the month starting 2026-03-01, sales were $28,357.22 [[Q1:R1]].", "For the period ending 2026-03-01, sales were $28,357.22 [[Q1:R1]]."),
        ("Period ended March 2026", "In the month of March 2026, sales were $28,357.22 [[Q1:R1]].", "For the period ended March 2026, sales were $28,357.22 [[Q1:R1]]."),
        ("Period ending March 2026", "During March 2026, sales declined by $53,803.23 [[Q1:R1]].", "During the period ending March 2026, sales declined by $53,803.23 [[Q1:R1]]."),
        ("Ended 2026-03", "For the month 2026-03, revenue was $12,450.00 [[Q1:R2]].", "For the period ended 2026-03, revenue was $12,450.00 [[Q1:R2]]."),
    ]
    for name, orig, mut in date_semantics:
        cases.append(MutationCase(f"date_semantic_{name}", "date_semantic", orig, mut, store))

    # Category 9: Unit Mismatch (percent vs absolute)
    unit_mismatches = [
        ("Percent instead of dollars", "Novaship revenue was $28,357.22 [[Q1:R1]].", "Novaship revenue was 28,357.22% [[Q1:R1]]."),
        ("Dollars instead of count", "There were 18 high tickets [[Q3:R2]].", "There were $18 high tickets [[Q3:R2]]."),
        ("Percent instead of count", "Customer placed 142 orders [[Q2:R1]].", "Customer placed 142% orders [[Q2:R1]]."),
        ("Percent instead of decline", "Novaship declined by $53,803.23 [[Q1:R1]].", "Novaship declined by 53,803.23% [[Q1:R1]]."),
    ]
    for name, orig, mut in unit_mismatches:
        cases.append(MutationCase(f"unit_mismatch_{name}", "unit_mismatch", orig, mut, store))

    # Category 10: Malformed Citations (ranges, nested brackets, grouped brackets)
    malformed_citations = [
        ("Range through syntax", "Results observed [[Q1:R1]] [[Q1:R2]].", "Results observed [[Q1:R1 through Q1:R2]]."),
        ("Range to syntax", "Results observed [[Q1:R1]] [[Q1:R2]].", "Results observed [[Q1:R1 to Q1:R2]]."),
        ("Grouped comma syntax", "Results observed [[Q1:R1]] [[Q1:R2]].", "Results observed [[Q1:R1, Q1:R2]]."),
        ("Nested triple brackets", "Sales were $28,357.22 [[Q1:R1]].", "Sales were $28,357.22 [[[Q1:R1]]]."),
        ("Range dot-dot syntax", "Results observed [[Q1:R1]] [[Q1:R2]].", "Results observed [[Q1:R1..Q1:R2]]."),
    ]
    for name, orig, mut in malformed_citations:
        cases.append(MutationCase(f"malformed_{name}", "malformed_citation", orig, mut, store))

    # Category 11: Derived Value Hallucinations (sum, diff, count arithmetic errors)
    derived_hallucinations = [
        ("Fake sum total", "Total revenue for Novaship and SecureVault was $96,457.22 [[Q1:R1]] [[Q1:R4]].", "Total revenue for Novaship and SecureVault was $125,000.00 [[Q1:R1]] [[Q1:R4]]."),
        ("Fake difference", "SecureVault outsold Novaship by $39,742.78 [[Q1:R1]] [[Q1:R4]].", "SecureVault outsold Novaship by $55,000.00 [[Q1:R1]] [[Q1:R4]]."),
        ("Fake row count", "Across 2 products analyzed [[Q1:R1]] [[Q1:R4]].", "Across 5 products analyzed [[Q1:R1]] [[Q1:R4]]."),
    ]
    for name, orig, mut in derived_hallucinations:
        cases.append(MutationCase(f"derived_{name}", "derived_value_error", orig, mut, store))

    # Category 12: Hand-Reviewed Adversarial & Subtly Corrupted Edge-Cases (WP-F3 Trust Upgrades)
    adversarial_edge_cases = [
        ("ticket_count_mismatch", "There were 18 high priority tickets [[Q3:R2]].", "There were 17 high priority tickets [[Q3:R2]]."),
        ("critical_ticket_zero", "Critical tickets logged were 4 [[Q3:R1]].", "Critical tickets logged were 0 [[Q3:R1]]."),
        ("medium_ticket_drift", "Medium priority tickets were 42 [[Q3:R3]].", "Medium priority tickets were 43 [[Q3:R3]]."),
        ("low_ticket_drift", "Low tickets totaled 110 [[Q3:R4]].", "Low tickets totaled 115 [[Q3:R4]]."),
        ("currency_drift_cent", "Novaship March revenue was $28,357.22 [[Q1:R1]].", "Novaship March revenue was $28,357.20 [[Q1:R1]]."),
        ("currency_drift_dollar", "CloudSync revenue reached $12,450.00 [[Q1:R2]].", "CloudSync revenue reached $12,451.00 [[Q1:R2]]."),
        ("securevault_revenue_drift", "SecureVault revenue was $68,100.00 [[Q1:R4]].", "SecureVault revenue was $68,100.50 [[Q1:R4]]."),
        ("dataflow_revenue_drift", "DataFlow revenue was $45,200.50 [[Q1:R3]].", "DataFlow revenue was $45,200.00 [[Q1:R3]]."),
        ("customer_count_mismatch", "Novaship served 85 customers [[Q2:R1]].", "Novaship served 86 customers [[Q2:R1]]."),
        ("customer_count_securevault", "SecureVault served 190 customers [[Q2:R2]].", "SecureVault served 189 customers [[Q2:R2]]."),
        ("customer_count_dataflow", "DataFlow had 115 customers [[Q2:R3]].", "DataFlow had 114 customers [[Q2:R3]]."),
        ("orders_count_mismatch", "Novaship handled 142 total orders [[Q2:R1]].", "Novaship handled 140 total orders [[Q2:R1]]."),
        ("orders_count_dataflow", "DataFlow processed 205 orders [[Q2:R3]].", "DataFlow processed 206 orders [[Q2:R3]]."),
        ("inverted_difference_drift", "SecureVault outsold Novaship by $39,742.78 [[Q1:R1]] [[Q1:R4]].", "SecureVault outsold Novaship by $41,500.00 [[Q1:R1]] [[Q1:R4]]."),
        ("multi_row_sum_drift_dollar", "Combined revenue for Novaship and CloudSync was $40,807.22 [[Q1:R1]] [[Q1:R2]].", "Combined revenue for Novaship and CloudSync was $40,808.22 [[Q1:R1]] [[Q1:R2]]."),
        ("multi_row_sum_three_products", "Sum of Novaship, CloudSync, and DataFlow was $86,007.72 [[Q1:R1]] [[Q1:R2]] [[Q1:R3]].", "Sum of Novaship, CloudSync, and DataFlow was $86,010.00 [[Q1:R1]] [[Q1:R2]] [[Q1:R3]]."),
        ("subtle_percentage_error", "Novaship accounts for 29.4% of combined sales [[Q1:R1]] [[Q1:R4]].", "Novaship accounts for 35.0% of combined sales [[Q1:R1]] [[Q1:R4]]."),
        ("total_tickets_all_priorities", "Across all four priority levels, 174 total tickets were received [[Q3:R1]] [[Q3:R2]] [[Q3:R3]] [[Q3:R4]].", "Across all four priority levels, 175 total tickets were received [[Q3:R1]] [[Q3:R2]] [[Q3:R3]] [[Q3:R4]]."),
        ("doc_duplicate_charge_drift", "Customer had duplicate charges of $120.00 [[D:tickets:TK-1002]].", "Customer had duplicate charges of $125.00 [[D:tickets:TK-1002]]."),
        ("currency_drift_euro_symbol", "Novaship March revenue was $28,357.22 [[Q1:R1]].", "Novaship March revenue was €28,357.22 [[Q1:R1]]."),
    ]
    for name, orig, mut in adversarial_edge_cases:
        cases.append(MutationCase(f"adversarial_{name}", "adversarial_edge_cases", orig, mut, store))

    return cases


def run_mutation_suite() -> MutationResult:
    """Run all mutation cases and report catch rates by category."""
    cases = build_mutation_suite()
    by_category: dict[str, dict[str, int]] = {}
    misses: list[dict[str, Any]] = []

    for case in cases:
        report = verify_citations(case.mutated_text, case.evidence_store)
        is_caught = not report.is_clean

        case.caught = is_caught
        cat = case.category
        if cat not in by_category:
            by_category[cat] = {"total": 0, "caught": 0, "missed": 0}

        by_category[cat]["total"] += 1
        if is_caught:
            by_category[cat]["caught"] += 1
        else:
            by_category[cat]["missed"] += 1
            misses.append({
                "name": case.name,
                "category": case.category,
                "mutated_text": case.mutated_text,
                "report_discrepancies": report.get_discrepancies(),
                "report_invalid_ids": report.get_invalid_ids(),
                "report_unsupported": report.get_unsupported_claims(),
            })

    total = len(cases)
    caught = sum(c["caught"] for c in by_category.values())
    missed = total - caught
    rate = (caught / total) * 100.0 if total > 0 else 0.0

    # Add catch rate percentage to category summary
    category_summary: dict[str, dict[str, Any]] = {}
    for cat, stats in by_category.items():
        c_rate = (stats["caught"] / stats["total"]) * 100.0 if stats["total"] > 0 else 0.0
        category_summary[cat] = {
            "total": stats["total"],
            "caught": stats["caught"],
            "missed": stats["missed"],
            "catch_rate_pct": round(c_rate, 1),
        }

    return MutationResult(
        total_mutations=total,
        caught_count=caught,
        missed_count=missed,
        catch_rate_pct=round(rate, 1),
        by_category=category_summary,
        misses=misses,
    )


def run_false_positive_suite() -> dict[str, Any]:
    """Test clean, valid answers containing incidental non-metric numbers to ensure 0% false positives."""
    store = create_seed_evidence_store()

    clean_test_cases = [
        "In Q1 2026, Novaship revenue was $28,357.22 [[Q1:R1]].",
        "During quarter 1 of 2025, ticket triage was updated.",
        "Error 504 gateway timeout was reported in customer logs [[D:tickets:TK-1002]].",
        "HTTP 502 bad gateway was resolved in version 2.4.",
        "Status 404 was returned on outdated API endpoints.",
        "On March 12th, the incident was closed.",
        "The team met on 12 March to review logs.",
        "The system downtime lasted for 4 hours before resolution.",
        "Average response time was 30 minutes for urgent cases.",
        "Ticket TK-1002 was submitted on 2026-03-01 [[D:tickets:TK-1002]].",
        "1. First, check the database credentials.",
        "2. Second, verify the schema models.",
        "Top 3 products were analyzed in the report.",
        "Software release v1.0.4 included security patches.",
        "In 2026, CloudSync dropped by $3,482.85 in revenue [[Q1:R2]].",
        "Across Q1 to Q4, operational metrics remained stable.",
        "Customers submitted bug BUG-404 during staging testing.",
        "For the month of March 2026, sales reached $28,357.22 [[Q1:R1]].",
        "During 2024, legacy systems were migrated.",
        "Resolution was achieved within 2 days of notification.",
    ]

    total = len(clean_test_cases)
    false_positives = 0
    fp_details = []

    for text in clean_test_cases:
        report = verify_citations(text, store)
        if not report.is_clean:
            false_positives += 1
            fp_details.append({
                "text": text,
                "discrepancies": report.get_discrepancies(),
                "unsupported": report.get_unsupported_claims(),
                "invalid_ids": report.get_invalid_ids(),
            })

    fp_rate = (false_positives / total) * 100.0 if total > 0 else 0.0
    return {
        "total_cases": total,
        "clean_passes": total - false_positives,
        "false_positives": false_positives,
        "false_positive_rate_pct": round(fp_rate, 2),
        "failures": fp_details,
    }


def print_mutation_report(result: MutationResult, fp_result: dict[str, Any]) -> str:
    """Format and print a markdown report of mutation and false-positive results."""
    lines = [
        "## Deterministic Verifier Mutation and Trust Report",
        "",
        f"- **Total Mutations Tested:** {result.total_mutations}",
        f"- **Mutations Caught:** {result.caught_count} ({result.catch_rate_pct}%)",
        f"- **Mutations Missed:** {result.missed_count}",
        "",
        "### Catch Rate by Failure Category",
        "",
        "| Category | Total | Caught | Missed | Catch Rate |",
        "|---|---|---|---|---|",
    ]

    for cat, stats in result.by_category.items():
        lines.append(f"| {cat} | {stats['total']} | {stats['caught']} | {stats['missed']} | {stats['catch_rate_pct']}% |")

    lines.extend([
        "",
        "### False-Positive Evaluation",
        "",
        f"- **Total Clean Test Sentences:** {fp_result['total_cases']}",
        f"- **Clean Passes (No Flags):** {fp_result['clean_passes']}",
        f"- **False Positives:** {fp_result['false_positives']}",
        f"- **False-Positive Rate:** {fp_result['false_positive_rate_pct']}%",
    ])

    if result.misses:
        lines.extend([
            "",
            "### Missed Mutations Details",
            "",
            "```json",
            json.dumps(result.misses, indent=2),
            "```",
        ])

    report_str = "\n".join(lines)
    return report_str


if __name__ == "__main__":
    mutation_res = run_mutation_suite()
    fp_res = run_false_positive_suite()
    print(print_mutation_report(mutation_res, fp_res))
