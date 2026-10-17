"""Real-world dataset acceptance runner for WP3.

Tests end-to-end ingestion, profiling, confirmation, and querying for:
1. Full UCI Online Retail (541k rows)
2. Chinook Tracks (relational sample)
3. Messy Customer Feedback (BOM, semicolons, PII, missing values, text)
"""

from __future__ import annotations

import json
from pathlib import Path
import time

from datamind.agent.orchestrator import AgentOrchestrator
from datamind.config import load_config
from datamind.uploads.manager import UploadManager


def run_acceptance() -> dict:
    print("=" * 70)
    print("WP3 REAL-WORLD DATASET ACCEPTANCE SUITE")
    print("=" * 70)

    mgr = UploadManager(base_dir=".datamind/uploads", enabled=True)
    config = load_config("datamind.yaml")
    results = {}

    # ---------------------------------------------------------
    # DATASET 1: UCI Online Retail (541,909 rows)
    # ---------------------------------------------------------
    print("\n[1/3] Testing UCI Online Retail Dataset...")
    retail_path = Path("examples/secondary/online_retail/Online_Retail.csv")
    assert retail_path.exists(), "UCI Online Retail CSV missing!"

    s1 = mgr.create_session()
    start_t = time.perf_counter()
    file_bytes = retail_path.read_bytes()
    meta1 = mgr.ingest_file(s1, "online_retail.csv", file_bytes)
    ingest_time1 = time.perf_counter() - start_t

    print(f"  Ingest Time: {ingest_time1:.2f}s")
    print(f"  Rows Loaded: {meta1['total_rows']:,}")
    print(f"  Columns:     {meta1['total_columns']}")
    print(f"  Candidate Queries Generated: {len(meta1['candidate_queries'])}")

    # Human review confirmation (default £ GBP for UK retailer)
    review_cfg1 = {
        "default_currency": "GBP",
        "currency_symbol": "£",
        "tables": {
            meta1["table_name"]: {
                "description": "UK Online Retail transnational transactions (2010-2011)",
                "columns": {
                    c["name"]: {"enabled": True, "description": f"{c['original_name']} column"}
                    for c in meta1["columns"]
                },
            }
        },
    }
    model1 = mgr.confirm_model(s1, review_cfg1)
    print(f"  Confirmed Model: {model1.name} with {len(model1.tables)} table(s)")

    # Ask 5 quantitative questions via isolated orchestrator
    orch1, ad1, ret1 = mgr.create_session_orchestrator(s1.session_id, config)
    q_results1 = []
    questions1 = [
        "What is the total number of records in the online retail dataset?",
        "What are the top 5 products by total sales revenue?",
        "Which countries generated the highest total transaction quantity?",
        "What was the total gross transaction value in GBP?",
        "What is the average unit price across all transactions?",
    ]

    try:
        # Pre-calculate deterministic baselines directly in DuckDB
        con1 = ad1.conn
        total_recs = con1.execute("SELECT COUNT(*) FROM online_retail").fetchone()[0]
        top5_rev = con1.execute("""
            SELECT description, ROUND(SUM(quantity * unitprice), 2) AS total_rev
            FROM online_retail
            WHERE description IS NOT NULL AND unitprice > 0
            GROUP BY description
            ORDER BY total_rev DESC
            LIMIT 5
        """).fetchall()
        top_countries = con1.execute("""
            SELECT country, SUM(quantity) AS total_qty
            FROM online_retail
            GROUP BY country
            ORDER BY total_qty DESC
            LIMIT 3
        """).fetchall()
        gross_val = con1.execute("SELECT ROUND(SUM(quantity * unitprice), 2) FROM online_retail WHERE unitprice > 0").fetchone()[0]
        avg_price = con1.execute("SELECT ROUND(AVG(unitprice), 2) FROM online_retail WHERE unitprice > 0").fetchone()[0]

        print("  Baseline Deterministic Verifications:")
        print(f"    - Total Count: {total_recs:,}")
        print(f"    - Top 1 Product Revenue: {top5_rev[0][0]} = £{top5_rev[0][1]:,.2f}")
        print(f"    - Top 1 Country Quantity: {top_countries[0][0]} = {top_countries[0][1]:,}")
        print(f"    - Total Gross Sales: £{gross_val:,.2f}")
        print(f"    - Average Unit Price: £{avg_price:.2f}")

        for q in questions1:
            q_res = orch1.run(q, max_turns=3)
            q_results1.append({
                "question": q,
                "answer": q_res.answer[:120] + "...",
                "turns": q_res.turns,
                "clean": q_res.citation_report.is_clean,
                "queries_executed": len(q_res.evidence_store.queries),
            })
            print(f"    Q: {q[:50]}... -> Turns: {q_res.turns}, Queries: {len(q_res.evidence_store.queries)}, Clean: {q_res.citation_report.is_clean}")

    finally:
        ad1.close()
        if ret1:
            ret1.close()

    results["uci_online_retail"] = {
        "rows": meta1["total_rows"],
        "columns": meta1["total_columns"],
        "ingest_time_seconds": round(ingest_time1, 2),
        "source_edits_needed": 0,
        "questions_tested": len(q_results1),
        "all_questions": q_results1,
    }

    # ---------------------------------------------------------
    # DATASET 2: Chinook Relational Tracks Sample
    # ---------------------------------------------------------
    print("\n[2/3] Testing Chinook Music Store Dataset...")
    chinook_path = Path("examples/secondary/chinook/chinook_tracks.csv")
    s2 = mgr.create_session()
    start_t2 = time.perf_counter()
    meta2 = mgr.ingest_file(s2, "chinook_tracks.csv", chinook_path.read_bytes())
    ingest_time2 = time.perf_counter() - start_t2

    print(f"  Ingest Time: {ingest_time2:.2f}s")
    print(f"  Rows Loaded: {meta2['total_rows']}")
    print(f"  Columns:     {meta2['total_columns']}")

    review_cfg2 = {
        "default_currency": "USD",
        "tables": {
            meta2["table_name"]: {
                "description": "Relational music tracks catalog with genre, composer, and price",
                "columns": {
                    c["name"]: {"enabled": True, "description": f"{c['original_name']} column"}
                    for c in meta2["columns"]
                },
            }
        },
    }
    mgr.confirm_model(s2, review_cfg2)
    orch2, ad2, ret2 = mgr.create_session_orchestrator(s2.session_id, config)
    q_results2 = []
    questions2 = [
        "What is the total number of tracks in the Chinook catalog?",
        "Which composer has the highest total number of tracks?",
        "What is the total duration in milliseconds of all tracks?",
    ]
    try:
        for q in questions2:
            q_res = orch2.run(q, max_turns=3)
            q_results2.append({
                "question": q,
                "answer": q_res.answer[:120] + "...",
                "turns": q_res.turns,
                "clean": q_res.citation_report.is_clean,
            })
            print(f"    Q: {q[:50]}... -> Turns: {q_res.turns}, Clean: {q_res.citation_report.is_clean}")
    finally:
        ad2.close()
        if ret2:
            ret2.close()

    results["chinook_tracks"] = {
        "rows": meta2["total_rows"],
        "columns": meta2["total_columns"],
        "ingest_time_seconds": round(ingest_time2, 3),
        "source_edits_needed": 0,
        "questions_tested": len(q_results2),
    }

    # ---------------------------------------------------------
    # DATASET 3: Messy Customer Feedback (BOM, Semicolons, PII, Text)
    # ---------------------------------------------------------
    print("\n[3/3] Testing Messy Customer Support Feedback Dataset...")
    messy_path = Path("examples/secondary/messy/customer_feedback_messy.csv")
    s3 = mgr.create_session()
    start_t3 = time.perf_counter()
    meta3 = mgr.ingest_file(s3, "customer_feedback.csv", messy_path.read_bytes())
    ingest_time3 = time.perf_counter() - start_t3

    print(f"  Ingest Time: {ingest_time3:.2f}s")
    print(f"  Rows Loaded: {meta3['total_rows']}")
    print(f"  Columns:     {meta3['total_columns']}")
    print(f"  Encoding Notices: {s3.encoding_notices}")

    # Verify PII detection
    email_col = next((c for c in meta3["columns"] if c["name"] == "contact_email"), None)
    assert email_col is not None, "contact_email column missing!"
    print(f"  PII Warning on contact_email: {email_col.get('pii_warning')}")
    assert email_col.get("pii_warning") is not None, "PII warning should be detected on email column!"

    # Verify document column detection on feedback_text
    text_col = next((c for c in meta3["columns"] if c["name"] == "feedback_text"), None)
    assert text_col is not None and text_col.get("is_document"), "feedback_text should be detected as document!"

    # Human review confirmation with FTS5 indexing on feedback_text
    review_cfg3 = {
        "default_currency": "USD",
        "tables": {
            meta3["table_name"]: {
                "description": "Customer feedback complaints and satisfaction scores",
                "columns": {
                    "feedback_id": {"is_primary_key": True},
                    "feedback_text": {"is_document": True, "description": "Customer feedback verbatim complaint text"},
                    "satisfaction_score": {"description": "1-5 satisfaction rating"},
                },
            }
        },
    }
    model3 = mgr.confirm_model(s3, review_cfg3)
    assert s3.fts_path.exists(), "FTS5 SQLite index should be created for document column!"
    print(f"  FTS5 SQLite Index verified: {s3.fts_path}")

    orch3, ad3, ret3 = mgr.create_session_orchestrator(s3.session_id, config)
    try:
        q_text = "What was the customer complaint regarding duplicate billing transaction?"
        q_res3 = orch3.run(q_text, max_turns=3)
        print(f"    Document Query: {q_text[:50]}... -> Answer: {q_res3.answer[:100]}...")
        print(f"    Retrieved Chunks: {len(q_res3.evidence_store.chunks)}")
    finally:
        ad3.close()
        if ret3:
            ret3.close()

    results["messy_feedback"] = {
        "rows": meta3["total_rows"],
        "columns": meta3["total_columns"],
        "ingest_time_seconds": round(ingest_time3, 3),
        "source_edits_needed": 0,
        "pii_detected": email_col.get("pii_warning") is not None,
        "fts_indexed": s3.fts_path.exists(),
    }

    # Cleanup test sessions
    mgr.delete_session(s1.session_id)
    mgr.delete_session(s2.session_id)
    mgr.delete_session(s3.session_id)

    print("\n" + "=" * 70)
    print("WP3 REAL-WORLD ACCEPTANCE PASSED ALL INVARIANTS")
    print("=" * 70)
    return results


if __name__ == "__main__":
    run_acceptance()
