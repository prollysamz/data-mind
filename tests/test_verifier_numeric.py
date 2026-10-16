"""Unit tests for deterministic numeric verifier and consistency checking."""

import pytest
from datamind.adapters.base import QueryResult
from datamind.agent.evidence import EvidenceStore
from datamind.agent.verifier import verify_citations


@pytest.fixture
def evidence_store():
    store = EvidenceStore()
    result = QueryResult(
        columns=["product_name", "order_month", "amount", "mom_revenue_decline"],
        rows=[
            ("Novaship", "2026-03-01", 28000.0, 53803.23),
            ("SecureVault", "2026-04-01", 68000.0, 5686.56),
        ],
        query_id="qid-test-123",
        elapsed_ms=12.5,
        truncated=False,
    )
    store.add_query("SELECT ...", "Test MoM decline", result)
    return store


def test_verified_numeric_match(evidence_store):
    text = "Novaship experienced the largest decline of $53,803.23 in 2026-03-01 [[Q1:R1]]."
    report = verify_citations(text, evidence_store)

    assert report.is_clean is True
    assert report.valid_count == 1
    assert report.verified_numbers_count >= 1
    assert report.discrepancy_count == 0
    assert report.unsupported_claims_count == 0

    num_check = report.numeric_checks[0]
    assert num_check.status == "VERIFIED"
    assert num_check.row_id == "Q1:R1"
    assert num_check.matched_column == "mom_revenue_decline"


def test_multiple_numbers_and_quantities(evidence_store):
    # Add an invoice query
    inv_result = QueryResult(
        columns=["line_no", "quantity", "amount"],
        rows=[
            (1, 6, 11.10),
            (2, 6, 11.10),
        ],
        query_id="qid-inv-456",
        elapsed_ms=5.0,
        truncated=False,
    )
    evidence_store.add_query("SELECT ...", "Invoice line items", inv_result)

    text = (
        "Item 1: quantity 6, amount 11.10 [[Q2:R1]]. "
        "Item 2: quantity 6, amount 11.10 [[Q2:R2]]."
    )
    report = verify_citations(text, evidence_store)
    assert report.is_clean is True
    assert report.valid_count == 2
    assert report.verified_numbers_count >= 2
    assert report.discrepancy_count == 0


def test_detect_numeric_discrepancy(evidence_store):
    # Model claims $99,999.00 but cited row only has 53803.23 and 28000.0
    text = "Novaship declined by a massive $99,999.00 [[Q1:R1]]."
    report = verify_citations(text, evidence_store)

    assert report.is_clean is False
    assert report.discrepancy_count == 1
    assert len(report.get_discrepancies()) == 1
    assert "99,999.00" in report.get_discrepancies()[0]


def test_detect_unsupported_numeric_claim(evidence_store):
    # Model asserts an arbitrary profit number without citing any query row
    text = "The overall company profits reached $450,000 this quarter."
    report = verify_citations(text, evidence_store)

    assert report.is_clean is False
    assert report.unsupported_claims_count == 1
    assert len(report.get_unsupported_claims()) == 1
    assert "450,000" in report.get_unsupported_claims()[0]


def test_bullet_and_calendar_year_not_flagged(evidence_store):
    # '1.' is a bullet, '2026' is a calendar year, 53803.23 is the verified number
    text = "1. In 2026, Novaship revenue decline was $53,803.23 [[Q1:R1]]."
    report = verify_citations(text, evidence_store)

    assert report.is_clean is True
    assert report.discrepancy_count == 0
    assert report.unsupported_claims_count == 0
    assert report.verified_numbers_count == 1


def test_currency_mismatch_detected(evidence_store):
    """Verify that claiming $738,876.88 when semantic model declares GBP (£) is marked a discrepancy."""
    from datamind.semantic.model import SemanticModel

    model_gbp = SemanticModel(
        name="retail_uk",
        description="UK retail dataset in GBP",
        default_currency="GBP",
        currency_symbol="£",
    )
    # Add revenue query result
    evidence_store.add_query(
        "SELECT SUM(amount) FROM SALES",
        "Total sales",
        QueryResult(
            columns=["total_revenue"],
            rows=[(738876.88,)],
            query_id="qid-curr-1",
            elapsed_ms=10.0,
            truncated=False,
        ),
    )

    # Agent wrote $738,876.88 instead of £738,876.88
    text = "Total sales reached $738,876.88 [[Q2:R1]]."
    report = verify_citations(text, evidence_store, semantic_model=model_gbp)

    assert report.is_clean is False
    assert report.discrepancy_count >= 1
    assert any("Currency unit mismatch" in d for d in report.get_discrepancies())


def test_date_semantic_period_ending_flagged(evidence_store):
    """Verify that 'period ending YYYY-MM-01' is caught because row represents month start."""
    text = "For the period ending 2026-03-01, Novaship declined by $53,803.23 [[Q1:R1]]."
    report = verify_citations(text, evidence_store)

    assert report.is_clean is False
    assert report.discrepancy_count >= 1
    assert any("Date semantic discrepancy" in d for d in report.get_discrepancies())
