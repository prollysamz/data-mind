"""Data egress guard, privacy sentinel enforcement, and outbound audit manifests."""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, ClassVar, Sequence

logger = logging.getLogger(__name__)


class DataEgressViolation(Exception):
    """Raised when data row contents, document text, or secret sentinels leak into an outbound cloud request."""
    pass


SENTINEL_ROW_SECRET = "SENTINEL_ROW_SECRET"  # pragma: allowlist secret -- planted test canary
SENTINEL_DOC_PASSCODE = "SENTINEL_DOC_PASSCODE"
SENTINEL_HIDDEN_COL_SECRET = "SENTINEL_HIDDEN_COL_SECRET"  # pragma: allowlist secret -- planted test canary
SENTINEL_PII_LEAK = "SENTINEL_PII_LEAK"


@dataclass
class EgressManifestItem:
    stage: str
    target_host: str
    model_id: str
    privacy_class: str
    tables_count: int = 0
    columns_count: int = 0
    verified_queries_count: int = 0
    data_rows_sent: int = 0
    documents_sent: int = 0
    prompt_bytes: int = 0
    tokens_estimated: int = 0
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EgressLedger:
    total_requests: int = 0
    total_bytes_sent: int = 0
    total_rows_sent: int = 0
    total_documents_sent: int = 0
    privacy_mode: str = "LOCAL_PRIVATE"
    items: list[EgressManifestItem] = field(default_factory=list)

    def record_request(self, item: EgressManifestItem) -> None:
        self.total_requests += 1
        self.total_bytes_sent += item.prompt_bytes
        self.total_rows_sent += item.data_rows_sent
        self.total_documents_sent += item.documents_sent
        self.items.append(item)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "total_bytes_sent": self.total_bytes_sent,
            "total_rows_sent": self.total_rows_sent,
            "total_documents_sent": self.total_documents_sent,
            "privacy_mode": self.privacy_mode,
            "is_air_gapped": self.total_rows_sent == 0 and self.total_documents_sent == 0 and all(i.privacy_class == "LOCAL_PRIVATE" for i in self.items),
            "summary": (
                "Air-Gapped: 0 bytes left your machine."
                if all(i.privacy_class == "LOCAL_PRIVATE" for i in self.items)
                else f"Cloud Metered: {self.total_rows_sent} data rows sent, {self.total_documents_sent} documents sent."
            ),
            "manifest": [i.to_dict() for i in self.items],
        }


class EgressSentinelGuard:
    """Enforces strict air-gap and schema-only isolation on outbound payloads."""

    KNOWN_SENTINELS: ClassVar[tuple[str, ...]] = (
        "SENTINEL_ROW_SECRET",
        "SENTINEL_DOC_PASSCODE",
        "SENTINEL_HIDDEN_COL_SECRET",
        "SENTINEL_PII_LEAK",
    )

    @classmethod
    def scan_text(cls, text: str) -> list[str]:
        """Scan text and return any detected planted canary trap secrets."""
        return [s for s in cls.KNOWN_SENTINELS if s in text]

    @classmethod
    def audit_outbound_payload(
        cls,
        messages: Sequence[dict[str, Any]],
        *,
        privacy_class: str,
        target_host: str,
        known_row_values: Sequence[str] | None = None,
        known_doc_passages: Sequence[str] | None = None,
    ) -> EgressManifestItem:
        """Inspect message contents to ensure no sensitive sentinels or row data leak when in private/hybrid mode."""
        payload_str = " ".join(str(m.get("content", "")) for m in messages)
        prompt_bytes = len(payload_str.encode("utf-8"))

        # 1. Sentinel Scan (Always fail closed on planted sentinels in hybrid/private mode)
        if privacy_class in ("LOCAL_PRIVATE", "HYBRID_PRIVACY", "CLOUD_METERED"):
            for sentinel in cls.KNOWN_SENTINELS:
                if sentinel in payload_str:
                    # In hybrid mode, sentinels from data/rows MUST NOT leave
                    raise DataEgressViolation(
                        f"Egress Sentinel Violation: Planted secret token '{sentinel}' detected in outbound request to {target_host}!"
                    )

        # 2. Check for leaked row contents in hybrid mode
        rows_sent = 0
        if known_row_values and privacy_class == "HYBRID_PRIVACY":
            for val in known_row_values:
                if len(str(val)) > 3 and str(val) in payload_str:
                    raise DataEgressViolation(
                        f"Hybrid Privacy Violation: Row data value '{val}' was included in schema-only prompt to {target_host}!"
                    )

        # 3. Check for leaked document chunks in hybrid mode
        docs_sent = 0
        if known_doc_passages and privacy_class == "HYBRID_PRIVACY":
            for doc in known_doc_passages:
                if len(doc) > 10 and doc in payload_str:
                    raise DataEgressViolation(
                        f"Hybrid Privacy Violation: Document chunk text was included in outbound prompt to {target_host}!"
                    )

        # Compute summary
        is_local = "localhost" in target_host or "127.0.0.1" in target_host
        actual_privacy = "LOCAL_PRIVATE" if is_local else "CLOUD_METERED"

        return EgressManifestItem(
            stage="sql_generation",
            target_host=target_host,
            model_id="dynamic",
            privacy_class=actual_privacy,
            data_rows_sent=rows_sent,
            documents_sent=docs_sent,
            prompt_bytes=prompt_bytes,
            summary="Local call: 0 rows, 0 docs egress" if is_local else "Cloud call: inspected by egress guard",
        )

    @classmethod
    def sanitize_sql_error(cls, error_msg: str, valid_identifiers: set[str] | None = None) -> str:
        """Strip raw literal values, customer numbers, and internal memory addresses from SQL errors for safe cloud repair."""
        # Replace string literals '...' with '<LITERAL>'
        sanitized = re.sub(r"'[^']*'", "'<REDACTED_LITERAL>'", error_msg)
        # Replace float/integer values not part of error codes with <NUM>
        sanitized = re.sub(r"(?<![A-Za-z0-9_])\d{3,}(?![A-Za-z0-9_])", "<REDACTED_ID>", sanitized)
        # Strip potential stack traces / system paths
        sanitized = re.sub(r"[A-Za-z]:\\[^\s\n]+", "<PATH>", sanitized)
        sanitized = re.sub(r"/[^\s\n]+", "<PATH>", sanitized)
        # Truncate
        return sanitized[:500]
