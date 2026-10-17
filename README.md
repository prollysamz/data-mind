# DataMind: Verifiable Enterprise AI Data Agent

> An open-source, verifiable AI data agent powered by **Google Gemma** and **Snowflake / DuckDB**. Natural language questions answered with executable SQL, interactive provenance citations, deterministic numeric verification, and automated data uploads.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-green.svg)](LICENSE)
[![Local First](https://img.shields.io/badge/execution-100%25%20local%20available-brightgreen.svg)](docs/local-only.md)
[![Deterministic Verifier](https://img.shields.io/badge/verifier-100%25%20mutation%20catch-blueviolet.svg)](eval/mutation.py)
[![Budget Guard](https://img.shields.io/badge/cost%20guard-fail--closed%20%2410%20cap-success.svg)](datamind.yaml)

---

## Problem and Thesis

Most "talk to your data" systems suffer from hallucinations, non-reproducible answers, unverified data claims, and silent directional errors (calling a decline an increase).

**DataMind wins on three core principles:**
1. **Trust:** Every claim carries its generated SQL, query ID, result rows, and document citations. A deterministic code verifier (not another LLM) parses every number, currency value, date semantic, and direction word in the answer and reconciles it against cited cells down to the exact cent.
2. **Proof:** Published, empirical evaluation metrics with complete provenance (git commit `5fc44b2`, date, model, backend, latency) and 100% transparent reporting of failures.
3. **Reusability:** Point DataMind at any schema in minutes, drag-and-drop CSV datasets with automated profiling and session isolation, or connect to other AI agents via the Model Context Protocol (MCP).

---

## Architecture

```
User Question (Browser UI / CLI / MCP)
   │
   ▼
[Planner] ──────► Classify (answerable / ambiguous / unanswerable), decompose into sub-questions
   │
   ▼
[Orchestrator] ──► Multi-step loop with strict tool calling
   │      ├─► tool: run_sql() ─────────► [SQL Guard (AST)] ──► [DB Adapter: DuckDB | Snowflake]
   │      └─► tool: search_documents() ─► [Retriever: SQLite FTS5]
   ▼
[Evidence Store] Stable IDs per cell (Q1:R1) and document chunk (D:doc:id)
   │
   ▼
[Narrator] ─────► Structured answer with citation tags [[Q1:R1]]
   │
   ▼
[Verifier] ─────► Deterministic Python: traces numbers, currency, dates & direction words
   │
   ▼
[API + UI] ─────► Answer, pure SVG charts, interactive table row highlights, SQL drawer, 3-state badges
```

---

## Quickstart (Under 5 Minutes)

### 1. Clone & Setup Virtual Environment
```bash
git clone https://github.com/mohit-hackoctober/DataMind.git
cd DataMind

# Create virtual environment
python -m venv .venv

# Activate (Windows PowerShell)
.\.venv\Scripts\Activate.ps1
# Activate (Linux / macOS)
# source .venv/bin/activate
```

### 2. Install Package
```bash
pip install -e ".[dev]"
```

### 3. Verify System Diagnostics
```bash
datamind doctor
```
Checks Python version, core dependencies, configuration, DuckDB, local Ollama (16k context window), client-side budget guard, and Snowflake connectivity.

### 4. Start the Interactive Web UI
```bash
datamind serve --enable-uploads --port 8080
```
Open **`http://localhost:8080`** in your browser.

---

## Evaluation & Empirical Benchmarks

All benchmark evaluations are deterministic, execute live against configured backends, and log full provenance. See [eval/HISTORY.md](eval/HISTORY.md) for full historical run reconstruction.

### Development & Iterated Benchmarks Summary
*Note: In accordance with our Authenticity Charter, the previously reported 15/20 score on `held_out_sealed.yaml` represents an **iterated score on a used test set**, not a clean unseen generalisation benchmark. The questions were authored by the coding agent and run across multiple iterations. A genuine sealed benchmark authored by an independent party will be evaluated once on frozen tag `eval-freeze-v2` in WP-F5.*

| Evaluation Suite | Question Count | Passed | Failed | Pass Rate | Provenance & Standard |
|---|:---:|:---:|:---:|:---:|---|
| **Used Set (`held_out_sealed.yaml`)** | **20** | **15** | **5** | **75.0%** | **Iterated on used set** (first run scored 6/10 = 60.0% at `2888eb7`). Not a generalisation number. |
| **Business Suite (`business.yaml`)** | **21** | **21** | **0** | **100.0%** | Development tuning set; verified to the exact cent. |
| **Trust Suite (`trust.yaml`)** | **6** | **6** | **0** | **100.0%** | Planted numbers, DROP injections, Cartesian joins. |
| **Automated Security Suite** | **50** | **50** | **0** | **100.0%** | Destructive SQL, CTE writes, file functions, Unicode, injection defenses. |
| **Verifier Mutation Suite** | **53** | **53** | **0** | **100.0%** | Self-authored synthetic mutation suite (perturbations, flips, swaps). |
| **False-Positive Control Suite** | **20** | **20** | **0** | **0.0% FP** | Clean years, versions, quarters, error codes not flagged. |
| **UCI Retail Ingestion (541k rows)** | **5** | **5** | **0** | **100.0%** | Real UCI dataset ingested in 1.95s, verified answers. |

---

### Deterministic Verifier Mutation Catch Rates

Tested using `datamind eval --suite verifier` against 53 automated adversarial mutations across 11 failure classes:

| Failure Category | Total Tested | Caught | Missed | Catch Rate |
|---|:---:|:---:|:---:|:---:|
| **Value Perturbation** (small dollar discrepancy) | 6 | 6 | 0 | **100.0%** |
| **Magnitude Change** (10x larger / 0.1x smaller) | 5 | 5 | 0 | **100.0%** |
| **Direction Word Flip** (decline vs growth) | 6 | 6 | 0 | **100.0%** |
| **Currency Symbol Swap** ($ to € or £) | 5 | 5 | 0 | **100.0%** |
| **Citation Swap** (citing wrong row) | 5 | 5 | 0 | **100.0%** |
| **Invalid Citation ID** (fabricated ID) | 5 | 5 | 0 | **100.0%** |
| **Deleted Citation** (bare number without tag) | 5 | 5 | 0 | **100.0%** |
| **Date Semantic Error** ("period ending" vs month start) | 4 | 4 | 0 | **100.0%** |
| **Unit Mismatch** (percentage vs currency/count) | 4 | 4 | 0 | **100.0%** |
| **Malformed Citation** (ranges, nested brackets) | 5 | 5 | 0 | **100.0%** |
| **Derived Value Arithmetic Error** (sum/diff/count error) | 3 | 3 | 0 | **100.0%** |
| **Total Mutations** | **53** | **53** | **0** | **100.0%** |

---

### Latency Profile (Uncached, Local Gemma E2B)

- **Median End-to-End Latency:** 2,264 ms
- **90th Percentile (p90) Latency:** 3,459 ms
- **Database Execution Overhead:** < 15 ms (DuckDB in-process) / ~250 ms (Snowflake cloud)

---

### Model-Swap Comparison

| Model | Deployment Target | Pass Rate on Sealed Set | Cost per 1k Questions |
|---|---|:---:|:---:|
| **Gemma 4 E2B (2B)** | Local Ollama / vLLM | 75.0% (15/20) | **$0.00** (Free) |
| **Gemma 4 26B-A4B** | Bedrock Mantle / vLLM | 95.0% (19/20) | ~$0.45 USD |
| **Gemma 4 31B** | Cloud API | 100.0% (20/20) | ~$0.90 USD |

---

## Interactive UI & Visualizations

- **Dependency-Free SVG Charts:** Generates clean, responsive bar charts, line charts, diverging variance charts, and KPI stat cards without external chart CDNs.
- **Interactive Provenance Highlighting:** Clicking any number in the answer or chart highlights the corresponding row in the SQL results table with a golden ring.
- **Verbatim Evidence Drawer:** Clicking a document citation pill (`[[D:SUPPORT_TICKETS:TK-1002]]`) slides out the original customer ticket with sentence highlights.
- **3-State Verification Badges:**
  - `VERIFIED (100% Grounded)`: All numbers and claims match live evidence.
  - `PARTIALLY VERIFIED`: Some numbers verified, optional advisory warnings noted.
  - `NOT VERIFIED / DISCREPANCY`: Discrepancy detected, with exact cell differences highlighted.
- **CSV Export:** Sanitize cell values to strictly prevent spreadsheet formula injection attacks (`=`, `+`, `-`, `@`).

---

## User-Uploaded Datasets & Security

Upload any custom CSV dataset live via drag-and-drop or the REST API:
1. **Session Isolation:** Uploaded datasets are stored in dedicated directories (`.datamind/uploads/<session_id>/data.duckdb`).
2. **Automated Profiling:** Detects column types, null percentages, distinct counts, min/max bounds, sample values, and flags potential PII (emails, phone numbers).
3. **Deterministic Semantic Drafting:** Automatically drafts descriptions, metric definitions, and verified candidate queries.
4. **FTS5 Document Indexing:** Text columns are indexed into SQLite FTS5 with chunk IDs `D:<table>:<pk>`.
5. **Instant Data Purge:** Click "Delete My Data" to immediately delete the session folder, DuckDB database, and search index.

---

## Model Context Protocol (MCP) Server

DataMind includes an official MCP stdio server for seamless integration with Cursor, Claude Desktop, and other agent systems:

```bash
datamind mcp
```

### Available MCP Tools:
- `datamind_ask`: Ask questions and receive verified answers with interactive citation tags.
- `datamind_list_tables`: List verified tables and metric definitions in the active semantic model.
- `datamind_describe_table`: Get column definitions, types, and descriptions.

---

## Privacy & Cost Controls

- **Client-Side Fail-Closed Guard:** Enforces hard budget ceiling ($10.00 USD total cap). Refuses cloud calls if the cap is reached.
- **Local-Only Guarantee:** In local mode, zero outbound requests are made; all prompts and data remain on localhost. See [docs/local-only.md](docs/local-only.md).
- **Idle Snowflake Suspension:** Run `datamind warehouse-suspend` to immediately suspend the Snowflake warehouse and eliminate idle compute charges.
- **Usage Metering:** Run `datamind usage` to view token consumption and dollar spend by day, model, and purpose.

---

## Limitations & Known Gaps

- **"Verified but Wrong" Silent Error Risk:** The deterministic verifier verifies that numbers, currencies, and dates in the response match cited cells in evidence. It does **not** prove that the generated SQL represents the logically correct business question (e.g., if a wrong filter or join fan-out produces self-consistent but incorrect numbers). Measuring this silent-wrong rate and catching it via query AST linting and second opinions is the core focus of WP-F3 and WP-F8.
- **Iterated Test Set:** The 15/20 score on `held_out_sealed.yaml` was iterated on during development and written by the coding agent itself; true zero-shot generalisation will be established only on the human-authored sealed set in WP-F5.
- **Synthetic Demo Data:** The primary demo (`examples/primary/demo.duckdb`) is synthetic data (1,450 rows, 100 tickets) where outages directly correlate with revenue drops. Authentic real-world validation on the Olist Brazilian E-Commerce dataset is introduced in WP-F1.
- **Snowflake Cortex Hosted Inference:** Snowflake trial accounts without AWS IAM linkage restrict hosted Cortex inference (`COMPLETE`); DataMind utilizes Gemma as the reasoning agent while Snowflake functions as the high-performance data execution layer.
- **Qualitative Causation:** The verifier deterministically checks numbers, currency, dates, and direction words, but does not prove statistical causation between customer complaint text and revenue changes.

---

## Documentation

- [Evaluation History & Integrity Log](eval/HISTORY.md)
- [Quickstart Guide](docs/quickstart.md)
- [Local-Only Air-Gapped Mode](docs/local-only.md)
- [Configuration Reference](docs/configuration.md)
- [Dataset Documentation & Licences](docs/datasets.md)
- [Adding an Adapter Guide](docs/adding-an-adapter.md)
- [3-Minute Video Demo Script](docs/demo-script.md)
- [Third-Party Notices](THIRD_PARTY_NOTICES.md)

---

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.

## Acknowledgements

- Google DeepMind Gemma team for open model weights and tool calling capabilities.
- Snowflake for data cloud infrastructure and hackathon sponsorship.
- UCI Machine Learning Repository for the Online Retail dataset.
