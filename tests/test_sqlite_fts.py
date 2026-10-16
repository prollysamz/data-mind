"""Unit tests for SQLite FTS5 document retriever."""

from pathlib import Path
import pytest

from datamind.retrieval.sqlite_fts import SQLiteFTSRetriever


def test_sqlite_fts_in_memory():
    retriever = SQLiteFTSRetriever(":memory:")
    cid1 = retriever.index_document(
        doc_name="DOCS",
        source_pk="101",
        content="Novaship encountered severe API latency and 504 gateway timeout issues.",
        metadata={"product": "Novaship", "severity": "High"},
    )
    cid2 = retriever.index_document(
        doc_name="DOCS",
        source_pk="102",
        content="CloudSync desktop app sync speed was optimized with parallel upload threads.",
        metadata={"product": "CloudSync", "severity": "Low"},
    )

    assert cid1 == "D:DOCS:101"
    assert cid2 == "D:DOCS:102"

    results = retriever.search("latency timeout", k=2)
    assert len(results) >= 1
    assert results[0].chunk_id == "D:DOCS:101"
    assert results[0].metadata["product"] == "Novaship"
    assert results[0].score > 0

    # Filter test
    filtered = retriever.search("sync latency", k=5, filters={"product": "CloudSync"})
    assert len(filtered) == 1
    assert filtered[0].chunk_id == "D:DOCS:102"


def test_sqlite_fts_build_from_duckdb():
    demo_db = Path("examples/primary/demo.duckdb")
    assert demo_db.exists()

    retriever = SQLiteFTSRetriever(":memory:", source_db_path=demo_db)
    retriever.build_index()

    # Search for outage
    results = retriever.search("Novaship outage downtime", k=5)
    assert len(results) >= 1
    assert any("Novaship" in r.text for r in results)
    assert all(r.chunk_id.startswith("D:SUPPORT_TICKETS:TK-") for r in results)


def test_sqlite_fts_empty_query():
    retriever = SQLiteFTSRetriever(":memory:")
    assert retriever.search("", k=5) == []
    assert retriever.search("   ", k=5) == []
