"""Unit tests for cryptographic answer receipts, SHA-256 hash chains, and tamper verification."""

import json

import pytest

from datamind.adapters.base import QueryResult
from datamind.adapters.duckdb_adapter import DuckDBAdapter
from datamind.agent.evidence import EvidenceStore
from datamind.agent.verifier import verify_citations
from datamind.guardrails.sql_guard import SQLGuard
from datamind.trust.receipts import ReceiptGenerator, ReceiptVerifier


@pytest.fixture
def sample_receipt():
    store = EvidenceStore()
    q_res = QueryResult(
        columns=["product_name", "amount"],
        rows=[("Novaship", 28357.22), ("SecureVault", 68100.00)],
        query_id="qid-rec-1",
        elapsed_ms=5.0,
        truncated=False,
    )
    store.add_query("SELECT product_name, amount FROM sales", "Product sales", q_res)
    answer = "Novaship generated $28,357.22 [[Q1:R1]] and SecureVault generated $68,100.00 [[Q1:R2]]."
    rep = verify_citations(answer, store)

    receipt = ReceiptGenerator.generate_receipt(
        question="What was revenue by product?",
        answer=answer,
        evidence_store=store,
        citation_report=rep,
        backend_name="duckdb",
        model_name="gemma4:e2b",
    )
    return receipt


def test_receipt_validates_clean(sample_receipt):
    res = ReceiptVerifier.verify(sample_receipt)
    assert res["verified"] is True
    assert res["status"] == "PASS"
    assert res["checks"]["answer_integrity"] is True
    assert res["checks"]["question_integrity"] is True
    assert res["checks"]["sql_steps_integrity"] is True
    assert res["checks"]["root_hash_integrity"] is True


def test_receipt_detects_answer_tampering(sample_receipt):
    # Alter 1 byte in the answer text
    tampered = dict(sample_receipt)
    tampered["answer"] = tampered["answer"].replace("$28,357.22", "$99,999.99")

    res = ReceiptVerifier.verify(tampered)
    assert res["verified"] is False
    assert res["status"] == "FAIL (Tampered)"
    assert res["checks"]["answer_integrity"] is False


def test_receipt_detects_sql_tampering(sample_receipt):
    # Alter 1 character in the embedded SQL steps
    tampered = dict(sample_receipt)
    tampered["sql_steps"] = list(tampered["sql_steps"])
    tampered["sql_steps"][0]["sql"] = "SELECT * FROM sales"

    res = ReceiptVerifier.verify(tampered)
    assert res["verified"] is False
    assert res["checks"]["sql_steps_integrity"] is False


def test_receipt_contains_no_secrets(sample_receipt):
    receipt_str = json.dumps(sample_receipt)
    for forbidden in ["password", "secret_key", "api_key", "token_auth"]:
        assert forbidden not in receipt_str.lower()


def test_receipt_html_export(sample_receipt):
    html = ReceiptGenerator.export_html(sample_receipt)
    assert "<!DOCTYPE html>" in html
    assert sample_receipt["root_hash"] in html
    assert "DataMind Cryptographic Receipt" in html


def test_receipt_html_export_escapes_untrusted_content(sample_receipt):
    receipt = dict(sample_receipt)
    receipt["answer"] = '<img src=x onerror="alert(1)">'
    receipt["metadata"] = dict(sample_receipt["metadata"])
    receipt["metadata"]["question"] = "<script>alert(1)</script>"

    html_output = ReceiptGenerator.export_html(receipt)

    assert "<script>alert(1)</script>" not in html_output
    assert '<img src=x onerror="alert(1)">' not in html_output
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_output


def test_receipt_replay_executes_guarded_sql(sample_receipt):
    adapter = DuckDBAdapter(":memory:")
    try:
        adapter.conn.execute("CREATE TABLE sales (product_name VARCHAR, amount DOUBLE)")
        adapter.conn.executemany(
            "INSERT INTO sales VALUES (?, ?)",
            [("Novaship", 28357.22), ("SecureVault", 68100.00)],
        )
        guard = SQLGuard(approved_tables={"sales"})

        result = ReceiptVerifier.replay(sample_receipt, adapter, guard)

        assert result["replay_success"] is True
        assert result["status"] == "DATA_IDENTICAL"
        assert result["findings"][0]["status"] == "MATCH"
    finally:
        adapter.close()
