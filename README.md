# DataMind: Talk to Your Data

> An open-source, verifiable AI data agent powered by Gemma and Snowflake. Natural-language questions answered with verifiable SQL, deterministic number checking, and interactive citations.

## Problem and Thesis

Most "talk to your data" systems suffer from hallucinations, non-reproducible answers, and unverified data claims.

**DataMind wins on three things:**
1. **Trust:** Every answer carries its generated SQL, query ID, result rows, and document citations. A deterministic program (not another LLM) verifies that every number in the answer traces directly to a result cell or a declared derivation.
2. **Proof:** Published, measured evaluation metrics with full reproducibility, including documented failure cases.
3. **Reusability:** A developer can point DataMind at their own schema in minutes with swappable LLM and database backends.

## Architecture

```
User Question
   │
   ▼
[Planner] ──────► Classify (answerable / ambiguous / unanswerable), decompose into sub-questions
   │
   ▼
[Orchestrator] ──► Multi-step loop with strict tool calling
   │      ├─► tool: run_sql() ─────────► [SQL Guard] ──► [DB Adapter: DuckDB | Snowflake]
   │      └─► tool: search_documents() ─► [Retriever: SQLite FTS5]
   ▼
[Evidence Store] Stable IDs per cell (Q1:R1) and document chunk (D:doc:id)
   │
   ▼
[Narrator] ─────► Structured answer with citation tags [[Q1:R1]]
   │
   ▼
[Verifier] ─────► Deterministic code: traces every number to cited cells
   │
   ▼
[API + UI] ─────► Answer, interactive citations, chart, SQL drawer, verification badges
```

## Quickstart

See [docs/quickstart.md](docs/quickstart.md) for full instructions (Windows PowerShell and Linux/macOS bash).

```bash
# 1. Clone & setup virtual environment
python -m venv .venv
# Activate:
# Windows PowerShell: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate

# 2. Install dependencies
pip install -e ".[dev]"

# 3. Configure environment
cp .env.example .env
# Edit .env with your keys

# 4. Verify system
python scripts/check_llm.py
datamind --help
```

## Configuration

Configuration is loaded from `datamind.yaml` with environment variable interpolation `${VAR}`.
**Precedence rule:** Environment variables (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_ORCHESTRATOR_MODEL`, etc.) strictly override values defined in YAML.

See [docs/configuration.md](docs/configuration.md) and [datamind.example.yaml](datamind.example.yaml).

## How It Works

- **SQL Guardrails:** AST parsing via `sqlglot`. Strictly single-statement `SELECT` only. Table allow-lists, join validation, statement timeouts, and row limits enforced before execution.
- **Evidence Store:** Every query execution receives an ID (`Q1`), and each row receives a stable identifier (`Q1:R1`). Document chunks retain `D:<doc>:<pk>`.
- **Deterministic Verifier:** Regex extracts numbers, currency, and percentages from narrative sentences and verifies them against cited cells within numeric tolerance or declared derivations.

## Evaluation

Evaluation suites are located in `eval/` and executed via `datamind eval`.
Results are saved to `eval/results/` and summarized in `eval/results/RESULTS.md`.

| Suite | Questions | Passed | Failed | Notes |
|---|---|---|---|---|
| Business Suite | TBD | TBD | TBD | Ground-truth SQL match |
| Trust Suite | TBD | TBD | TBD | Planted errors, prompt injection, refusals |

## Limitations

- **Cortex Hosted Inference:** On Snowflake trial accounts, `COMPLETE` and `AI_COMPLETE` are restricted; DataMind uses Gemma (via Bedrock Mantle, Ollama, or OpenAI-compatible endpoints) for NL-to-SQL generation while Snowflake serves as the execution data layer.
- **Cortex Search / Analyst:** Supported as optional adapters only when verified available on the account.

## How to Add an Adapter

See [docs/adding-an-adapter.md](docs/adding-an-adapter.md) for implementing `DBAdapter`.

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Acknowledgements

- Google Gemma team for open model weights and tool calling capabilities.
- Snowflake for data cloud infrastructure.
