"""Conservative detection of explicit instruction-override and credential-exfiltration requests.

This is defense in depth, not a proof that arbitrary prompt injection is detectable.
Database permissions and SQL allowlists remain the execution boundary.
"""

import re
import unicodedata

PATTERNS = (
    r"\b(?:ignore|override|disregard)\b.{0,40}\b(?:previous|system|developer|security|all)\b.{0,25}\b(?:instructions|rules|prompt|restrictions)\b",
    r"\b(?:reveal|print|exfiltrate|send|show|dump)\s+(?:(?:all|the|my|your|our|saved|configured|current|me|us)\s+){0,4}(?:api[ _-]?keys?|passwords?|credentials|environment variables|system prompt|access tokens?)\b",
)


def injection_flags(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = "".join(c for c in normalized if unicodedata.category(c) != "Cf")
    normalized = " ".join(normalized.lower().split())
    return [f"instruction_pattern_{i}" for i, pattern in enumerate(PATTERNS, 1) if re.search(pattern, normalized)]
