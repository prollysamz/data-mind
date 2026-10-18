"""Opt-in live smoke test: synthetic CSV -> Snowflake -> Gemma -> evidence -> cleanup.

Uses real credentials and warehouse credits. Never runs as part of pytest.
"""

from __future__ import annotations

import argparse
import json

from datamind.config import load_config
from datamind.uploads.manager import UploadManager


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="datamind_snowflake.yaml")
    args = parser.parse_args()
    config = load_config(args.config)
    if config.backend.type != "snowflake" or "gemma" not in config.llm.orchestrator_model.lower():
        parser.error("Use a Snowflake configuration with a Gemma model.")
    manager = UploadManager(base_dir=".datamind/verification-uploads", enabled=True, config=config)
    # Check loader login before creating any session. A read-only user cannot provision it.
    try:
        with manager.snowflake_store._loader() as loader:
            loader.execute("SELECT CURRENT_ROLE()")
    except Exception:
        print("Loader login failed. Grant DATAMIND_LOADER or configure both SNOWFLAKE_LOADER_USER and SNOWFLAKE_LOADER_PASSWORD.")
        return 1
    session = manager.create_session()
    outcome = 0
    try:
        metadata = manager.ingest_file(session, "upload_smoke.csv", b"id,amount\n1,12.5\n2,20\n")
        manager.confirm_model(session, {})
        orchestrator, adapter, retriever = manager.create_session_orchestrator(session.session_id, config)
        try:
            result = orchestrator.run("What is the total amount in upload_smoke?")
            receipts = [q.result.query_id for q in result.evidence_store.queries]
            if not result.success or not result.citation_report.is_clean or not receipts or "unknown-sfqid" in receipts:
                raise RuntimeError("Gemma did not produce a clean answer backed by live Snowflake evidence")
            if session.db_path.exists():
                raise RuntimeError("Unexpected local database in a Snowflake upload session")
            print(json.dumps({
                "storage": metadata["storage"], "model": config.llm.orchestrator_model,
                "answer": result.answer, "evidence": result.evidence_store.to_json(),
            }, indent=2, default=str))
        finally:
            adapter.close()
            if retriever:
                retriever.close()
    except Exception as exc:
        print(f"Live upload verification failed: {type(exc).__name__}: {exc}")
        outcome = 1
    finally:
        try:
            manager.delete_session(session.session_id)
            print("Verification schema deleted.")
        except Exception:
            print(f"Cleanup failed; retain session {session.session_id} and retry deletion after reconnecting.")
            outcome = 1
    return outcome


if __name__ == "__main__":
    raise SystemExit(main())
