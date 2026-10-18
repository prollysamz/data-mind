"""Unit tests for SQLite FTS5 document retriever."""

from pathlib import Path

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


def test_sqlite_fts_multithreaded_search_regression():
    """Regression test: SQLite connection created on one thread must not raise
    sqlite3.ProgrammingError when searched from worker threads in ThreadingHTTPServer.
    """
    from concurrent.futures import ThreadPoolExecutor

    # Initialize retriever on main thread
    retriever = SQLiteFTSRetriever(":memory:")
    retriever.index_document(
        doc_name="SUPPORT_TICKETS",
        source_pk="TK-1002",
        content="Novaship customers experienced 504 gateway timeout errors on March 12.",
        metadata={"product": "Novaship"},
    )

    def worker_search(query_str: str):
        return retriever.search(query_str, k=3)

    # Execute searches across 8 worker threads concurrently
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker_search, "Novaship 504 timeout") for _ in range(16)]
        for f in futures:
            results = f.result()
            assert len(results) == 1
            assert results[0].chunk_id == "D:SUPPORT_TICKETS:TK-1002"
            assert "Novaship" in results[0].text

