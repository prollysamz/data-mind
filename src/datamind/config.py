"""Configuration schema and loader for DataMind.

Enforces environment variable interpolation and strict precedence:
environment variables override YAML values.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
import yaml


ENV_PATTERN = re.compile(r"\$\{([A-Za-z0-9_]+)(?::-(.*?))?\}")


def load_dotenv(dotenv_path: str | Path = ".env") -> None:
    """Load variables from .env file into os.environ if not already set."""
    p = Path(dotenv_path)
    if not p.exists():
        return
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v


def _interpolate_env(value: Any) -> Any:
    """Recursively interpolate ${VAR} and ${VAR:-default} from environment."""
    if isinstance(value, str):
        def replace(match: re.Match) -> str:
            var_name = match.group(1)
            default = match.group(2) if match.group(2) is not None else ""
            return os.getenv(var_name, default)
        return ENV_PATTERN.sub(replace, value)
    elif isinstance(value, dict):
        return {k: _interpolate_env(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_interpolate_env(v) for v in value]
    return value


class BudgetConfig(BaseModel):
    """Budget and cost guard configuration."""
    max_usd_total: float | None = None
    max_usd_per_run: float | None = None
    max_calls_per_run: int | None = None
    max_tokens_per_call: int | None = 16384
    max_calls_per_minute: int | None = 60
    price_per_million_input_usd: float | None = None
    price_per_million_output_usd: float | None = None

    @field_validator(
        "max_usd_total",
        "max_usd_per_run",
        "max_calls_per_run",
        "max_tokens_per_call",
        "max_calls_per_minute",
        "price_per_million_input_usd",
        "price_per_million_output_usd",
        mode="before",
    )
    @classmethod
    def empty_str_to_none(cls, v: Any) -> Any:
        if isinstance(v, str) and not v.strip():
            return None
        return v


class LLMConfig(BaseModel):
    """LLM client configuration."""
    base_url: str = Field(default="http://localhost:11434/v1")
    api_key_env: str = Field(default="LLM_API_KEY")
    api_key: str | None = None
    orchestrator_model: str = Field(default="google.gemma-4-26b-a4b")
    reasoning_model: str = Field(default="google.gemma-4-31b")
    fast_model: str = Field(default="google.gemma-4-e2b")
    token_param: Literal["max_tokens", "max_completion_tokens"] = Field(default="max_tokens")
    max_tokens: int = Field(default=8192)
    temperature: float = Field(default=0.0)
    timeout_seconds: float = Field(default=60.0)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)

    def get_api_key(self) -> str:
        """Resolve API key from direct field or environment variable."""
        if self.api_key:
            return self.api_key
        return os.getenv(self.api_key_env, os.getenv("LLM_API_KEY", ""))


class SnowflakeConfig(BaseModel):
    """Snowflake connection parameters (credentials from env vars)."""
    model_config = ConfigDict(populate_by_name=True)

    account_env: str = "SNOWFLAKE_ACCOUNT"
    user_env: str = "SNOWFLAKE_USER"
    password_env: str = "SNOWFLAKE_PASSWORD"
    role: str = "DATAMIND_READONLY"
    warehouse: str = "DATAMIND_XS"
    database: str = ""
    schema_: str = Field(default="", alias="schema")

    @property
    def schema(self) -> str:
        return self.schema_

    def get_account(self) -> str:
        return os.getenv(self.account_env, "")

    def get_user(self) -> str:
        return os.getenv(self.user_env, "")

    def get_password(self) -> str:
        return os.getenv(self.password_env, "")


class BackendConfig(BaseModel):
    """Database backend configuration."""
    type: Literal["duckdb", "snowflake"] = "duckdb"
    duckdb_path: str = "examples/primary/demo.duckdb"
    snowflake: SnowflakeConfig = Field(default_factory=SnowflakeConfig)


class GuardrailsConfig(BaseModel):
    """Guardrails settings."""
    max_rows: int = 1000
    statement_timeout_seconds: float = 30.0
    max_plan_cost: float | None = None


class AgentConfig(BaseModel):
    """Agent loop settings."""
    max_steps: int = 6
    max_sql_repairs: int = 2
    max_tokens_per_question: int = Field(default=32768)


class RetrievalConfig(BaseModel):
    """Retrieval settings."""
    index_path: str = ".datamind/fts.sqlite"
    top_k: int = 5


class AppConfig(BaseModel):
    """Root application configuration."""
    llm: LLMConfig = Field(default_factory=LLMConfig)
    backend: BackendConfig = Field(default_factory=BackendConfig)
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    semantic_model: str = "examples/primary/semantic_model.yaml"
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)


def apply_env_overrides(config: AppConfig) -> AppConfig:
    """Apply environment variable overrides according to precedence rules.

    Precedence: Environment variables override YAML values for:
    - LLM_BASE_URL
    - LLM_API_KEY
    - LLM_ORCHESTRATOR_MODEL
    - LLM_REASONING_MODEL
    - LLM_FAST_MODEL
    """
    if env_val := os.getenv("LLM_BASE_URL"):
        config.llm.base_url = env_val
    if env_val := os.getenv("LLM_API_KEY"):
        config.llm.api_key = env_val
    if env_val := os.getenv("LLM_ORCHESTRATOR_MODEL"):
        config.llm.orchestrator_model = env_val
    if env_val := os.getenv("LLM_REASONING_MODEL"):
        config.llm.reasoning_model = env_val
    if env_val := os.getenv("LLM_FAST_MODEL"):
        config.llm.fast_model = env_val
    return config


def load_config(config_path: str | Path | None = None, load_env: bool = True) -> AppConfig:
    """Load configuration from YAML file and apply environment variable overrides."""
    if load_env:
        load_dotenv()
    data: dict[str, Any] = {}
    if config_path is not None:
        path = Path(config_path)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                raw_data = yaml.safe_load(f) or {}
                data = _interpolate_env(raw_data)

    config = AppConfig.model_validate(data)
    return apply_env_overrides(config)
