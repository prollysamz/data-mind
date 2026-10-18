"""Unit tests for Data Egress Sentinel Guard and privacy enforcement."""

import pytest

from datamind.guardrails.egress_guard import DataEgressViolation, EgressLedger, EgressManifestItem, EgressSentinelGuard


def test_egress_sentinel_blocks_secret_token():
    messages = [
        {"role": "system", "content": "You are a data assistant."},
        {"role": "user", "content": "Process this data: SENTINEL_ROW_SECRET_12345 in column"},
    ]
    with pytest.raises(DataEgressViolation) as exc:
        EgressSentinelGuard.audit_outbound_payload(
            messages,
            privacy_class="HYBRID_PRIVACY",
            target_host="bedrock.amazonaws.com",
        )
    assert "Planted secret token" in str(exc.value)


def test_egress_blocks_row_data_in_hybrid_mode():
    messages = [
        {"role": "user", "content": "Question with leaked row: Customer secret name JohnDoePrivate"},
    ]
    with pytest.raises(DataEgressViolation) as exc:
        EgressSentinelGuard.audit_outbound_payload(
            messages,
            privacy_class="HYBRID_PRIVACY",
            target_host="bedrock.amazonaws.com",
            known_row_values=["JohnDoePrivate"],
        )
    assert "Hybrid Privacy Violation" in str(exc.value)


def test_local_egress_manifest_records_clean_audit():
    messages = [
        {"role": "user", "content": "What was total revenue?"},
    ]
    item = EgressSentinelGuard.audit_outbound_payload(
        messages,
        privacy_class="LOCAL_PRIVATE",
        target_host="localhost:11434",
    )
    assert item.data_rows_sent == 0
    assert item.documents_sent == 0
    assert item.privacy_class == "LOCAL_PRIVATE"
    assert "Local call: 0 rows, 0 docs egress" in item.summary


def test_sql_error_sanitization():
    raw_error = "Syntax error in query: SELECT * FROM users WHERE ssn = '123-45-6789' AND path = C:\\Windows\\System32"
    sanitized = EgressSentinelGuard.sanitize_sql_error(raw_error)
    assert "123-45-6789" not in sanitized
    assert "<REDACTED_LITERAL>" in sanitized or "<REDACTED_ID>" in sanitized
    assert "C:\\Windows\\System32" not in sanitized


def test_egress_ledger_air_gap_reporting():
    ledger = EgressLedger()
    item1 = EgressManifestItem(stage="sql", target_host="localhost", model_id="gemma4:e2b", privacy_class="LOCAL_PRIVATE", prompt_bytes=100)
    ledger.record_request(item1)
    d = ledger.to_dict()
    assert d["is_air_gapped"] is True
    assert "0 bytes left your machine" in d["summary"]
