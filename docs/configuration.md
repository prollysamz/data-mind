# DataMind Configuration Guide

DataMind is configured via `datamind.yaml` with support for environment variable interpolation and strict environment variable overrides.

## Configuration Precedence

DataMind enforces strict precedence:
1. **Environment Variables**: Always override values from YAML files.
2. **YAML File (`datamind.yaml`)**: Primary configuration specification.
3. **Internal Defaults**: Fallback values when neither is specified.

The environment variables that override configuration include:
- `LLM_BASE_URL`: Base URL for OpenAI-compatible endpoint.
- `LLM_API_KEY`: API key for LLM provider.
- `LLM_ORCHESTRATOR_MODEL`: Model name for multi-turn planning and tool calling.
- `LLM_REASONING_MODEL`: Model name for complex analytical reasoning.
- `LLM_FAST_MODEL`: Model name for quick classification and entity extraction.
- `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD`: Snowflake connection credentials.

---

## Example Configuration (`datamind.yaml`)

```yaml
# Database backend
backend:
  type: duckdb                    # "duckdb" or "snowflake"
  duckdb_path: examples/primary/demo.duckdb
  snowflake:
    account_env: SNOWFLAKE_ACCOUNT
    user_env: SNOWFLAKE_USER
    password_env: SNOWFLAKE_PASSWORD
    role: DATAMIND_READONLY
    warehouse: DATAMIND_XS
    database: DATAMIND
    schema: PUBLIC

# Semantic data model
semantic_model: examples/primary/semantic_model.yaml

# Document retrieval
retrieval:
  index_path: .datamind/fts.sqlite
  top_k: 5

# Guardrails and safety invariants
guardrails:
  max_rows: 1000
  statement_timeout_seconds: 30.0

# Agent planner loop
agent:
  max_steps: 6
  max_sql_repairs: 2

# LLM inference endpoint
llm:
  base_url: ${LLM_BASE_URL:-http://localhost:11434/v1}
  orchestrator_model: ${LLM_ORCHESTRATOR_MODEL:-gemma4:e2b}
  fast_model: ${LLM_FAST_MODEL:-gemma4:e2b}
  token_param: max_tokens        # "max_tokens" or "max_completion_tokens"
  max_tokens: 4096
  temperature: 0.0
  timeout_seconds: 60.0
  thinking: false                # allow Gemma/Qwen thinking mode on local Ollama (default off; see below)
```

`thinking: false` sends `reasoning_effort: none` to local servers. Thinking tokens count against `max_tokens`, so with thinking on a small model can spend the whole completion budget reasoning and return an empty reply (`finish_reason=length`).

---

## Interpolation Syntax

You can reference environment variables anywhere in the YAML using:
- `${VAR_NAME}`: Evaluates to `os.environ["VAR_NAME"]` (or empty string if unset).
- `${VAR_NAME:-default_value}`: Evaluates to `default_value` if `VAR_NAME` is not set in the environment.
