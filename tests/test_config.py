"""Tests for configuration loading, interpolation, and environment precedence."""

from pathlib import Path

import pytest

from datamind.config import AppConfig, load_config


def test_env_interpolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test that ${VAR} and ${VAR:-default} are properly interpolated."""
    monkeypatch.setenv("TEST_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("TEST_ACC", "my_snowflake_acc")

    yaml_content = """
llm:
  base_url: ${TEST_BASE_URL}
  orchestrator_model: ${TEST_MODEL:-default-model-123}
backend:
  type: snowflake
  snowflake:
    account_env: ${TEST_ACC}
"""
    config_file = tmp_path / "datamind.yaml"
    config_file.write_text(yaml_content, encoding="utf-8")

    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_ORCHESTRATOR_MODEL", raising=False)

    cfg = load_config(config_file, load_env=False)
    assert cfg.llm.base_url == "https://api.example.com/v1"
    assert cfg.llm.orchestrator_model == "default-model-123"
    assert cfg.backend.snowflake.account_env == "my_snowflake_acc"


def test_config_precedence_env_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Test required by Phase 0:

    Environment variables (LLM_BASE_URL, LLM_API_KEY, LLM_ORCHESTRATOR_MODEL,
    LLM_REASONING_MODEL, LLM_FAST_MODEL) MUST strictly override YAML values.
    """
    yaml_content = """
llm:
  base_url: http://yaml-url:8000/v1
  orchestrator_model: yaml-orchestrator-model
  reasoning_model: yaml-reasoning-model
  fast_model: yaml-fast-model
"""
    config_file = tmp_path / "datamind.yaml"
    config_file.write_text(yaml_content, encoding="utf-8")

    # Set overriding environment variables
    monkeypatch.setenv("LLM_BASE_URL", "http://env-override-url:9999/v1")
    monkeypatch.setenv("LLM_API_KEY", "mock-test-key")  # pragma: allowlist secret
    monkeypatch.setenv("LLM_ORCHESTRATOR_MODEL", "google.gemma-4-26b-a4b")
    monkeypatch.setenv("LLM_REASONING_MODEL", "google.gemma-4-31b")
    monkeypatch.setenv("LLM_FAST_MODEL", "google.gemma-4-e2b")

    cfg = load_config(config_file)

    assert cfg.llm.base_url == "http://env-override-url:9999/v1"
    assert cfg.llm.api_key == "mock-test-key"  # pragma: allowlist secret
    assert cfg.llm.get_api_key() == "mock-test-key"  # pragma: allowlist secret
    assert cfg.llm.orchestrator_model == "google.gemma-4-26b-a4b"
    assert cfg.llm.reasoning_model == "google.gemma-4-31b"
    assert cfg.llm.fast_model == "google.gemma-4-e2b"


def test_token_param_config():
    """Test token_param can be max_tokens or max_completion_tokens."""
    cfg = AppConfig()
    assert cfg.llm.token_param == "max_tokens"
    cfg.llm.token_param = "max_completion_tokens"
    assert cfg.llm.token_param == "max_completion_tokens"


def test_snowflake_env_overrides_yaml(monkeypatch, tmp_path):
    from datamind.config import load_config

    cfg_file = tmp_path / "cfg.yaml"
    cfg_file.write_text(
        "backend:\n  type: snowflake\n  snowflake:\n    role: YAML_ROLE\n    warehouse: YAML_WH\n"
        "    database: YAML_DB\n    schema: YAML_SCHEMA\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SNOWFLAKE_ROLE", "ENV_ROLE")
    monkeypatch.setenv("SNOWFLAKE_WAREHOUSE", "ENV_WH")
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "ENV_DB")
    monkeypatch.setenv("SNOWFLAKE_SCHEMA", "ENV_SCHEMA")

    sf = load_config(cfg_file, load_env=False).backend.snowflake
    assert (sf.role, sf.warehouse, sf.database, sf.schema) == ("ENV_ROLE", "ENV_WH", "ENV_DB", "ENV_SCHEMA")


def test_retrieval_source_defaults_to_backend_duckdb_and_can_be_overridden(tmp_path):
    from datamind.config import load_config

    cfg_file = tmp_path / "cfg.yaml"
    cfg_file.write_text("backend:\n  duckdb_path: a.duckdb\n", encoding="utf-8")
    assert load_config(cfg_file, load_env=False).retrieval_source_path() == "a.duckdb"

    cfg_file.write_text(
        "backend:\n  type: snowflake\nretrieval:\n  source_duckdb_path: data/olist/olist.duckdb\n",
        encoding="utf-8",
    )
    assert load_config(cfg_file, load_env=False).retrieval_source_path() == "data/olist/olist.duckdb"
