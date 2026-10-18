# DataMind Configuration Guide

DataMind is configured via `datamind.yaml` with support for environment variable interpolation and strict environment variable overrides.

## Web UI model providers

Open the gear icon in the top-right corner to choose one of three providers:

- **Local model** fetches the models installed in Ollama from its local `/api/tags` endpoint.
  Select any installed model and refresh the list after pulling or deleting models.
- **OpenRouter** accepts an OpenRouter API key and lists the text-capable models currently
  advertised with zero prompt, completion, and request prices. Requests also carry a zero-price
  ceiling so a model leaving the free catalogue fails instead of silently becoming paid.
- **Google AI Studio** accepts a Gemini API key, fetches the compatible Gemini text models
  available to that key, and uses Google's OpenAI-compatible endpoint. If only a key is saved,
  Data Mind selects the first compatible model returned by Google.

**Test provider** sends a small request through the active saved provider. The web selection
applies to connected-data and uploaded-data questions, and does not alter CLI configuration or
installed models. With OpenRouter or Google active, questions, schema information, required SQL
rows, and retrieved documents may leave the machine. Review the provider's data policy first.

Keys are stored in plaintext in the gitignored `.datamind/settings.json` and are never returned
by the settings API. Protect access to this file. `DATAMIND_SETTINGS_PATH` changes its location.
Environment alternatives are `OPENROUTER_API_KEY` and either `GOOGLE_API_KEY` or
`GEMINI_API_KEY`. Removing a saved key does not remove an environment key. Failed saves leave
the previous settings unchanged.

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
  answerability_check: true          # screen questions against the semantic model before any SQL
  answerability_llm_fallback: true   # short JSON classification call when the screen is inconclusive

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

### Answerability screen

Before the agent loop, each new question is compared with a vocabulary built from the semantic model (table, column and metric names and descriptions):

- names nothing measurable ("How are the numbers looking?") → a clarifying question whose examples are the model's metrics;
- every content word matches the schema → straight to the SQL agent, no extra call;
- some words don't match → one short classification call to the orchestrator model returns `answerable` / `unanswerable` / `ambiguous`. A refusal is only accepted when it names at least one of the unmatched words; clarification only when nothing in the question matched. If the call fails, the question is refused only when none of its words match the schema.

Nothing here is dataset-specific: pointing `semantic_model` at another YAML changes what counts as answerable.

### Semantic model keys used by the query linter

The linter's fan-out and default-filter checks read their rules from the semantic model:

```yaml
tables:
  - name: orders
    primary_key: [order_id]          # marks the "one" side of joins on order_id
    default_filters:                 # optional; flagged when a query on this table omits it
      - column: order_status
        values: [delivered]
        description: Revenue counts delivered orders only.
        exempt_terms: [canceled, shipped]   # question words that lift the default
joins:
  - from_table: order_items
    to_table: orders
    on_condition: order_items.order_id = orders.order_id
    relationship: many_to_one        # optional; inferred from primary keys when omitted
```

Without primary keys (or `relationship`) on a join, fan-out can't be judged for it and the check is skipped; tables without `default_filters` get no default-filter check. A question that mentions the filter column itself (e.g. "by status") also lifts the default.

---

## Interpolation Syntax

You can reference environment variables anywhere in the YAML using:
- `${VAR_NAME}`: Evaluates to `os.environ["VAR_NAME"]` (or empty string if unset).
- `${VAR_NAME:-default_value}`: Evaluates to `default_value` if `VAR_NAME` is not set in the environment.
