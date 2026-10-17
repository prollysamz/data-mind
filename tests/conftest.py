"""Global test configuration and fixtures for DataMind.

Enforces Section 1 (Authenticity Charter):
- Tests never touch the real usage ledger, .env, or production databases.
- Test runs use temporary usage and cache files.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest


@pytest.fixture(autouse=True)
def isolate_test_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Enforce isolated temporary paths for usage ledger and LLM response cache during all tests."""
    test_usage_file = tmp_path / "isolated_test_usage.json"
    test_cache_db = tmp_path / "isolated_test_cache.sqlite"
    monkeypatch.setenv("DATAMIND_USAGE_PATH", str(test_usage_file))
    monkeypatch.setenv("DATAMIND_CACHE_PATH", str(test_cache_db))
    yield
