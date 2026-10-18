"""Record live query-tag, historical-read and loader-access checks without writes.

Run: python scripts/verify_snowflake_depth.py
Only result counts and execution receipts are saved; no credentials or source rows.
This is a historical-read check, not evidence of a data-change demonstration.
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from datamind.adapters import build_adapter
from datamind.config import load_config
from datamind.uploads.snowflake_store import SnowflakeUploadStore


def verify(config_path: str) -> dict:
    config = load_config(config_path)
    if config.backend.type != "snowflake":
        raise ValueError("This check requires a Snowflake config")
    tag = "datamind:verification:" + uuid.uuid4().hex[:12]
    config.backend.snowflake.query_tag = tag
    report = {"timestamp": datetime.now(UTC).isoformat(), "query_tag": tag}
    with build_adapter(config) as adapter:
        current = adapter.execute("SELECT COUNT(*) FROM SALES")
        report["current"] = {"count": current.rows[0][0], "query_id": current.query_id}
        # sfqid comes only from Snowflake, never from a user prompt.
        historical = adapter.execute(
            f"SELECT COUNT(*) FROM SALES BEFORE (STATEMENT => '{current.query_id}')"
        )
        report["time_travel_read"] = {
            "status": "PASS" if current.rows == historical.rows else "DIFFERENT",
            "count": historical.rows[0][0], "query_id": historical.query_id,
            "statement_anchor": current.query_id,
            "limitation": "No mutation performed; this does not prove answer freshness after changes.",
        }
        history = adapter.execute(
            "SELECT QUERY_ID, QUERY_TAG FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY_BY_SESSION(RESULT_LIMIT => 100)) "
            f"WHERE QUERY_ID = '{current.query_id}'"
        )
        report["query_tag_history"] = {
            "status": "PASS" if history.rows and history.rows[0][1] == tag else "NOT_VERIFIED",
            "query_id": history.query_id,
            "tag_seen": history.rows[0][1] if history.rows else None,
        }
    try:
        with SnowflakeUploadStore(config)._loader() as loader:
            loader.execute("SELECT CURRENT_ROLE()")
        report["loader_access"] = {"status": "PASS"}
    except Exception as exc:
        report["loader_access"] = {
            "status": "BLOCKED", "error_code": getattr(exc, "errno", None),
            "action": "Grant DATAMIND_LOADER to the ingestion login, or set separate loader credentials.",
        }
    report["data_change_demo"] = {"status": "NOT_RUN", "requires": "loader_access PASS"}
    report["dynamic_masking"] = {
        "status": "NOT_VERIFIED",
        "setup": "scripts/snowflake_governance_demo.sql (admin and Enterprise edition required)",
    }
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="datamind_snowflake.yaml")
    parser.add_argument("--output", default="eval/evidence/snowflake_depth.json")
    args = parser.parse_args()
    result = verify(args.config)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
