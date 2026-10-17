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


def test_direction_snowflake_incorrect_claims_flagged():
    """Verify that claiming 'decline' for products that grew (or 'increase' for products that dropped) is caught."""
    store = EvidenceStore()
    sf_result = QueryResult(
        columns=["product_name", "order_month", "prev_month_sales", "monthly_sales", "mom_revenue_decline"],
        rows=[
            ("SecureVault", "2026-03-01", 72053.67, 74077.77, -2024.10),
            ("OmniChat", "2026-03-01", 28056.62, 28111.03, -54.41),
            ("DataFlow", "2026-03-01", 63273.91, 59791.06, 3482.85),
            ("Novaship", "2026-03-01", 82160.45, 28357.22, 53803.23),
            ("CloudSync", "2026-03-01", 45343.78, 47955.77, -2611.99),
        ],
        query_id="qid-sf-mom",
        elapsed_ms=198.4,
        truncated=False,
    )
    store.add_query("SELECT ...", "Snowflake MoM Query", sf_result)

    # 1. Claiming SecureVault declined when revenue actually increased ($72k -> $74k)
    text_bad_secure = "SecureVault experienced a decline of $2,024.10 [[Q1:R1]]."
    rep1 = verify_citations(text_bad_secure, store)
    assert rep1.is_clean is False
    assert rep1.discrepancy_count >= 1
    assert any("Direction discrepancy" in d for d in rep1.get_discrepancies())

    # 2. Claiming DataFlow had revenue increase when revenue actually dropped ($63k -> $59k)
    text_bad_dataflow = "DataFlow experienced a revenue increase of $3,482.85 [[Q1:R3]]."
    rep2 = verify_citations(text_bad_dataflow, store)
    assert rep2.is_clean is False
    assert rep2.discrepancy_count >= 1
    assert any("Direction discrepancy" in d for d in rep2.get_discrepancies())

    # 3. Claiming CloudSync declined when revenue increased ($45k -> $47k)
    text_bad_cloud = "CloudSync experienced a decline of $2,611.99 [[Q1:R5]]."
    rep3 = verify_citations(text_bad_cloud, store)
    assert rep3.is_clean is False
    assert rep3.discrepancy_count >= 1
    assert any("Direction discrepancy" in d for d in rep3.get_discrepancies())


def test_direction_snowflake_correct_claims_verified():
    """Verify that correctly described directions (increase vs decline) pass verification."""
    store = EvidenceStore()
    sf_result = QueryResult(
        columns=["product_name", "order_month", "prev_month_sales", "monthly_sales", "mom_revenue_decline"],
        rows=[
            ("SecureVault", "2026-03-01", 72053.67, 74077.77, -2024.10),
            ("DataFlow", "2026-03-01", 63273.91, 59791.06, 3482.85),
            ("Novaship", "2026-03-01", 82160.45, 28357.22, 53803.23),
            ("CloudSync", "2026-03-01", 45343.78, 47955.77, -2611.99),
        ],
        query_id="qid-sf-correct",
        elapsed_ms=150.0,
        truncated=False,
    )
    store.add_query("SELECT ...", "Snowflake MoM Query", sf_result)

    correct_text = (
        "Novaship experienced a decline of $53,803.23 [[Q1:R3]]. "
        "DataFlow experienced a decline of $3,482.85 [[Q1:R2]]. "
        "SecureVault experienced an increase of $2,024.10 [[Q1:R1]]. "
        "CloudSync experienced an increase of $2,611.99 [[Q1:R4]]."
    )
    report = verify_citations(correct_text, store)
    assert report.is_clean is True
    assert report.discrepancy_count == 0
    assert report.verified_numbers_count == 4


def test_non_metrics_excluded_from_verification():
    """Verify that dates (March 12), HTTP error codes (504), and durations (4 hours) are NOT counted as verified metrics."""
    store = EvidenceStore()
    from datamind.retrieval.base import Chunk
    store.add_chunks(
        "outage timeout",
        [
            Chunk(
                chunk_id="D:SUPPORT_TICKETS:TK-1002",
                doc_name="SUPPORT_TICKETS",
                text="On March 12, customers experienced 504 gateway timeout errors for 4 hours.",
                score=1.5,
            )
        ]
    )

    # Narrative containing date, error code, duration
    text = "On March 12, customers reported 504 gateway timeout errors for 4 hours [[D:SUPPORT_TICKETS:TK-1002]]."
    report = verify_citations(text, store)

    assert report.is_clean is True
    assert report.valid_count == 1
    # Crucial assertion: non-metrics must NOT inflate the verified numbers count!
    assert report.verified_numbers_count == 0
    assert report.discrepancy_count == 0
    assert report.unsupported_claims_count == 0


def test_date_semantic_period_ending_month_name_flagged(evidence_store):
    """Verify that 'period ending March 2026' is caught and flagged as a date semantic discrepancy."""
    text1 = "For the period ending March 2026, Novaship declined by $53,803.23 [[Q1:R1]]."
    rep1 = verify_citations(text1, evidence_store)
    assert rep1.is_clean is False
    assert rep1.discrepancy_count >= 1
    assert any("Date semantic discrepancy" in d for d in rep1.get_discrepancies())
    assert any("period ending March 2026" in d for d in rep1.get_discrepancies())

    text2 = "For the period ended March 2026, Novaship declined by $53,803.23 [[Q1:R1]]."
    rep2 = verify_citations(text2, evidence_store)
    assert rep2.is_clean is False
    assert rep2.discrepancy_count >= 1
    assert any("Date semantic discrepancy" in d for d in rep2.get_discrepancies())


def test_date_semantic_valid_phrasing_passes(evidence_store):
    """Verify that correct phrasing ('for the month of March 2026') passes verification."""
    text = "For the month of March 2026, Novaship declined by $53,803.23 [[Q1:R1]]."
    report = verify_citations(text, evidence_store)
    assert report.is_clean is True
    assert report.discrepancy_count == 0
    assert report.verified_numbers_count == 1
def test_adversarial_wrong_plain_counts_flagged():
    """Adversarial test: verify that hallucinated plain integer counts (e.g. '5 tickets' when there are 4) are strictly flagged as discrepancies."""
    store = EvidenceStore()
    ticket_result = QueryResult(
        columns=["ticket_count"],
        rows=[(4,)],
        query_id="qid-tickets-count",
        elapsed_ms=5.0,
        truncated=False,
    )
    store.add_query("SELECT COUNT(*) FROM SUPPORT_TICKETS WHERE priority = 'Critical'", "Count critical tickets", ticket_result)

    # 1. Hallucinated ticket count: claims 5 tickets when query returned 4
    bad_text = "There were 5 tickets logged for critical issues [[Q1:R1]]."
    bad_report = verify_citations(bad_text, store)
    assert bad_report.is_clean is False
    assert bad_report.discrepancy_count == 1
    assert "claimed 5 does not match data in cited sources ['Q1:R1']" in bad_report.get_discrepancies()[0]

    # 2. Correct ticket count: claims 4 tickets -> passes
    good_text = "There were 4 tickets logged for critical issues [[Q1:R1]]."
    good_report = verify_citations(good_text, store)
    assert good_report.is_clean is True
    assert good_report.discrepancy_count == 0
    assert good_report.verified_numbers_count == 1

    # 3. Hallucinated order count: claims 10 orders when query returned 8
    order_result = QueryResult(
        columns=["order_count"],
        rows=[(8,)],
        query_id="qid-orders-count",
        elapsed_ms=4.0,
        truncated=False,
    )
    store.add_query("SELECT COUNT(DISTINCT order_id) FROM SALES", "Count orders", order_result)
    bad_order_text = "The customer placed 10 orders this quarter [[Q2:R1]]."
    bad_order_rep = verify_citations(bad_order_text, store)
    assert bad_order_rep.is_clean is False
    assert bad_order_rep.discrepancy_count == 1
    assert "claimed 10 does not match data in cited sources ['Q2:R1']" in bad_order_rep.get_discrepancies()[0]
