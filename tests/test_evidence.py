"""Tests for EvidenceStore provenance IDs and cell lookup."""

import pytest
from datamind.adapters.base import QueryResult
from datamind.agent.evidence import EvidenceStore
from datamind.retrieval.base import Chunk


def test_evidence_store_query_and_cells():
    """Verify Q<n>:R<m> IDs and cell lookup."""
    store = EvidenceStore()
    qr1 = QueryResult(
        columns=["product_name", "revenue", "order_month"],
        rows=[
            ("Alpha", 1000.50, "2026-01-01"),
            ("Beta", 2500.00, "2026-01-01"),
        ],
        query_id="sf-query-12345",
        elapsed_ms=12.5,
        truncated=False,
    )
    q1_label = store.add_query("SELECT * FROM SALES", "fetch sales", qr1)
    assert q1_label == "Q1"

    # Verify cell lookups
    assert store.get_cell("Q1:R1", "product_name") == "Alpha"
    assert store.get_cell("Q1:R1", "revenue") == 1000.50
    assert store.get_cell("Q1:R2", "product_name") == "Beta"

    # Verify case-insensitive column lookup
    assert store.get_cell("Q1:R1", "PRODUCT_NAME") == "Alpha"
    assert store.get_cell("Q1:R1", "Product_Name") == "Alpha"

    # Verify get_row
    row1 = store.get_row("Q1:R1")
    assert row1["product_name"] == "Alpha"
    assert row1["revenue"] == 1000.50

    # Verify error on non-existent row or column
    with pytest.raises(KeyError):
        store.get_cell("Q1:R99", "product_name")
    with pytest.raises(KeyError):
        store.get_cell("Q1:R1", "non_existent_col")


def test_evidence_store_multiple_queries():
    """Verify sequential query labels Q1, Q2, etc."""
    store = EvidenceStore()
    qr1 = QueryResult(columns=["colA"], rows=[("v1",)], query_id="q1", elapsed_ms=1.0, truncated=False)
    qr2 = QueryResult(columns=["colB"], rows=[("v2",)], query_id="q2", elapsed_ms=2.0, truncated=False)

    lbl1 = store.add_query("SELECT 1", "test1", qr1)
    lbl2 = store.add_query("SELECT 2", "test2", qr2)

    assert lbl1 == "Q1"
    assert lbl2 == "Q2"
    assert store.get_cell("Q1:R1", "colA") == "v1"
    assert store.get_cell("Q2:R1", "colB") == "v2"


def test_evidence_store_chunks():
    """Verify document chunk addition and lookup."""
    store = EvidenceStore()
    chunk1 = Chunk(
        chunk_id="D:tickets:TK-101",
        doc_name="tickets",
        text="Customer complaining about login failure.",
        metadata={"category": "auth", "created_at": "2026-03-01"},
    )
    chunk_ids = store.add_chunks("login failure", [chunk1])
    assert chunk_ids == ["D:tickets:TK-101"]

    retrieved = store.get_chunk("D:tickets:TK-101")
    assert retrieved is not None
    assert retrieved.text == "Customer complaining about login failure."
    assert store.has_id("D:tickets:TK-101")
    assert not store.has_id("D:tickets:TK-999")


def test_evidence_store_to_json():
    """Verify serialization to JSON structure."""
    store = EvidenceStore()
    qr = QueryResult(
        columns=["x", "y"],
        rows=[(1, 2)],
        query_id="test-id",
        elapsed_ms=5.0,
        truncated=False,
    )
    store.add_query("SELECT 1", "purpose", qr)
    store.add_chunks("q", [Chunk("D:doc:1", "doc", "some text")])

    data = store.to_json()
    assert "queries" in data
    assert len(data["queries"]) == 1
    assert data["queries"][0]["label"] == "Q1"
    assert data["queries"][0]["row_ids"] == ["Q1:R1"]
    assert "chunks" in data
    assert len(data["chunks"]) == 1
    assert data["chunks"][0]["chunk_id"] == "D:doc:1"
