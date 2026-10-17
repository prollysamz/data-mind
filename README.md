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

## Datasets & Demos

### 1. Primary Demo: Synthetic SaaS Sales & Support
- **Path:** `examples/primary/demo.duckdb`
- **Type:** **Synthetic Demo Data**.
- **Description:** 1,450 synthetic sales transactions across 5 products with 10 synthetic customer support tickets describing outages and billing friction for Novaship. Demonstrates mixed structured SQL and unstructured text retrieval.

### 2. Secondary Demo: Sampled UCI Online Retail Dataset
- **Path:** `examples/secondary/online_retail/`
- **Type:** **Real Transactional Data** (Sampled from the public GitHub mirror of the UC Irvine Online Retail dataset).
- **Description:** 31,456 transnational transactions occurring between 01/12/2010 and 09/12/2011 for a UK-based non-store online retailer in GBP (£). Note: The full UCI repository archive contains 541,909 rows (~528k clean rows); this demo uses a 31,456-row streaming sample to demonstrate schema introspection (`datamind init`) and structured analytical queries without ticket text.


## Evaluation

Evaluation suites are located in `eval/` and executed via `datamind eval`.
Results are saved to `eval/results/` and summarized in `eval/results/RESULTS.md`.

### Benchmark Scorecard (Dated: 2026-10-17)

**Model:** `gemma4:e2b` (Local Ollama) | **Backend:** DuckDB & Snowflake  
**Evaluation Standard:** Deterministic Value-Based Ground-Truth Result Set Comparison & Provenance Verification

#### Headline: Sealed Held-Out Generalization (Run Once, Frozen Config, Zero Tuning)

| Suite | Questions | Passed | Failed | Pass Rate (%) | Evaluation Notes |
|---|:---:|:---:|:---:|:---:|---|
| **Sealed Held-Out Suite** | **10** | **6** | **4** | **60.0%** | **Unseen generalisation benchmark**. 4 failures reflect Gemma 2B boundaries on multi-table joins and subquery aggregations without fine-tuning. |

#### Tuned & Verified Suites (Before vs. After Semantic Hints & Prompt Guidance)

| Suite | Initial Baseline | Post-Tuning Score | Delta | Verification Notes |
|---|:---:|:---:|:---:|---|
| **Business Suite** | 17 / 21 (81.0%) | **21 / 21 (100.0%)** | +4 | Fixed via CTE column aliasing, signed MoM polarity, and unit price formulas |
| **Held-Out Fresh Suite** | 6 / 10 (60.0%) | **10 / 10 (100.0%)** | +4 | Fixed via distinct counting and catalog join hints |
| **Trust & Adversarial Suite** | 6 / 6 (100.0%) | **6 / 6 (100.0%)** | 0 | Planted numbers, DROP TABLE injections, cartesian joins, ambiguous query clarification |

Full machine-generated run report: [eval/results/RESULTS.md](eval/results/RESULTS.md).

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
