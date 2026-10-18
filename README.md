# DataMind: Verifiable Enterprise AI Data Agent

> An open-source, verifiable AI data agent powered by **Google Gemma** and **Snowflake / DuckDB**. Natural language questions answered with executable SQL, interactive provenance citations, deterministic numeric verification, and automated data uploads.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
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
git clone https://github.com/prollysamz/data-mind.git
cd data-mind

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

# Generate the deterministic local DuckDB fixture required by the app and tests
python examples/primary/build_demo_data.py
```

For exactly the tested dependency versions, install from the lockfile instead: `pip install -r requirements.lock && pip install -e . --no-deps`.

On Linux/macOS, `bash scripts/setup_local.sh` does the whole setup (venv, pinned install, demo data, 16k-context Gemma model, `.env`, tests, diagnostics). On Windows, `powershell -ExecutionPolicy Bypass -File scripts/setup_local.ps1` performs the environment creation, install, demo-data build, test run, and diagnostics in one step. The default local model is Google Gemma (`gemma4:e2b`, run `ollama pull gemma4:e2b` first); override it with `-Model <ollama-model>` to try another Gemma variant. Gemma is a hard requirement of the hackathon track, so non-Gemma models are for experimentation only.

### 3. Verify System Diagnostics
```bash
datamind doctor
```
Checks Python version, core dependencies, configuration, DuckDB, local Ollama (verifies a >=8k context window is configured), client-side budget guard, and Snowflake connectivity.

### 4. Start the Interactive Web UI
```bash
datamind serve --enable-uploads --port 8080
```
Open **`http://localhost:8080`** in your browser.

### 5. Run on Snowflake (required for the hackathon track)
Follow [docs/snowflake.md](docs/snowflake.md): one bootstrap script creates the warehouse, database, read-only and loader roles, and a credit cap; then `datamind serve --config datamind_snowflake.yaml` runs every query in Snowflake and shows its Snowflake query ID.

### 6. See the answer follow the data
```bash
python scripts/demo_data_change.py                          # DuckDB, on a temporary copy
python scripts/demo_data_change.py datamind_snowflake.yaml  # Snowflake
```
Asks the same question before and after inserting one sales row, then removes it. A recorded DuckDB run is in [eval/evidence/data_change_duckdb.txt](eval/evidence/data_change_duckdb.txt).

---

## Tested Environment

| Component | Version / size |
|---|---|
| OS | Windows 11 Home (build 26300) |
| CPU / RAM | Intel Core i9-13900HX / 16 GB |
| GPU | NVIDIA GeForce RTX 4070 Laptop GPU (8 GB VRAM) |
| Python | 3.11.9 (dependencies pinned in [requirements.lock](requirements.lock)) |
| Ollama | 0.40.1 |
| Model | `gemma4:e2b` (Gemma 4 E2B, 4.6B parameters, Q4_K_M, 4.6 GB download; Apache-2.0), run as `gemma4-e2b-16k` with `num_ctx 16384` |
| Data | DuckDB 1.5.6 (local); Snowflake trial account (cloud backend) |

Business-suite questions took about 1-5 s each with the model on this GPU. The Linux/macOS setup script is provided but has not been run on those platforms.

---

## Evaluation & Empirical Benchmarks

All benchmark evaluations are deterministic, execute live against configured backends, and log full provenance. See [eval/HISTORY.md](eval/HISTORY.md) for full historical run reconstruction.

### Empirical Benchmarks Summary

| Evaluation Suite | Question Count | Passed | Failed | Pass Rate | Provenance & Standard |
|---|:---:|:---:|:---:|:---:|---|
| **Olist Development Benchmark (`olist_dev.yaml`)** | **30** | — | — | **Under re-run** | Earlier 100% figure came from a hard-coded SQL lane that bypassed Gemma and has been removed (see [eval/HISTORY.md](eval/HISTORY.md) §E). To be re-run through Gemma on DuckDB and Snowflake. |
| **Business Suite (`business.yaml`)** | **21** | **19-21** | **0-2** | **90.5-100%** | Synthetic DuckDB data, local `gemma4:e2b` with a 16k context window, five runs on 2026-10-18 after removing dev-set answers from the prompt (20, 20, 19, 21, 20 of 21). Development tuning set, not a generalisation figure. `Q_MONTHLY_REVENUE_TREND` usually fails (groups by product as well as month; now flagged PARTIALLY_VERIFIED); `Q_MIXED_REVENUE_SUPPORT` fails intermittently. |
| **Trust & Guardrails Suite (`trust.yaml`)** | **6** | **6** | **0** | **100.0%** | Planted numbers, DROP injections, Cartesian joins. |
| **Automated Security Suite (`tests/test_security.py`)** | **50** | **50** | **0** | **100.0%** | Destructive SQL, CTE writes, file functions, Unicode, injection defenses. |
| **Deterministic Verifier Mutation Suite** | **73** | **73** | **0** | **100.0%** | Comprehensive mutation suite (12 failure classes caught 100%). |
| **False-Positive Control Suite** | **20** | **20** | **0** | **0.0% FP** | Clean years, versions, quarters, error codes not flagged. |
| **Review Sentiment Agreement (Olist)** | **200** | **106** | **94** | **53.0%** | Local Gemma agreement vs customer star ratings (Negative Precision: 80.0%, Positive: 89.5%). |
| **Review Topic Accuracy (Olist)** | **50** | **40** | **10** | **80.0%** | 6 topic categories with `model_derived = true` persistence. |
| **UCI Retail Ingestion (541k rows)** | **5** | **5** | **0** | **100.0%** | Real UCI dataset ingested in 1.95s, verified answers. |

---

### Deterministic Verifier Mutation Catch Rates

Tested using `datamind eval --suite verifier` against 73 automated adversarial mutations across 12 failure classes:

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
| **Adversarial Edge Cases** (commas, rounding, prefix) | 20 | 20 | 0 | **100.0%** |
| **Total Mutations** | **73** | **73** | **0** | **100.0%** |

---

### Verifiable Trust & Model Registry Features (WP-F8)

1. **Model Presets & Privacy Modes:**
   - `local`: 100% Air-Gapped execution via local Ollama (`gemma4:e2b`). 0 bytes egress.
   - `hybrid_privacy`: Schema-only prompts to cloud; 0 data rows and 0 documents ever leave the machine.
   - `cloud_accuracy`: High-accuracy SQL generation on Amazon Bedrock Mantle.
   - `second_opinion`: Dual-model query evaluation with AST difference reporting.
2. **Data Egress Sentinel Guard:**
   - Intercepts planted secret canary tokens (`SENTINEL_ROW_SECRET`), sanitizes SQL error traces before cloud repair, and records an immutable egress audit manifest.
3. **Cryptographic Tamper-Evident Receipts:**
   - Every answer generates a SHA-256 digest hash chain covering question, SQL queries, evidence rows, verifier report, and egress manifest.
   - Verifiable offline via standalone WebCrypto HTML exporter or CLI replay (`datamind verify-receipt <file> --replay`).
4. **Live Red-Team Adversarial Challenge:**
   - An interactive in-browser challenge button that attacks the answer with 6 live corruptions (value perturbation, currency swap, magnitude scale, fabricated citation, deleted citation, direction flip) and verifies a 100% verifier catch rate live.

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

## Documentation & Work Package Reports

### Core Documentation:
- [Quickstart Guide](docs/quickstart.md)
- [Local-Only Air-Gapped Mode](docs/local-only.md)
- [Configuration Reference](docs/configuration.md)
- [Dataset Documentation & Licences](docs/datasets.md)
- [Adding an Adapter Guide](docs/adding-an-adapter.md)
- [3-Minute Video Demo Script](docs/demo-script.md)
- [Evaluation History & Integrity Log](eval/HISTORY.md)
- [Third-Party Notices](THIRD_PARTY_NOTICES.md)

### Work Package (WP) Technical Reports:
- [**Master Work Package Index**](docs/WP-SUMMARY-INDEX.md)
- [WP-F0: Integrity Reset & Authenticity Charter](docs/WP-F0-Integrity-Charter.md)
- [WP-F1: Authentic Data Ingestion (Olist Brazilian E-Commerce)](docs/WP-F1-Authentic-Data-Ingestion.md)
- [WP-F2: Small Model Tuning & Reasoning Scaffolding](docs/WP-F2-Small-Model-Tuning.md)
- [WP-F3: Trust & Groundedness Upgrades (AST Linter & 73/73 Mutations)](docs/WP-F3-Trust-Groundedness-Upgrades.md)
- [WP-F4: Review Classification & Sentiment Agreement](docs/WP-F4-Review-Classification-Sentiment.md)
- [WP-F5: Sealed Evaluation & 40-Item Human Citation Audit](docs/WP-F5-Sealed-Evaluation-Human-Audit.md)
- [WP-F6: Demonstration Script & MCP Integration](docs/WP-F6-Demo-Script-And-Presentation.md)
- [WP-F7: Packaging, System Diagnostics & Version Freeze](docs/WP-F7-Packaging-And-Artifact-Freeze.md)
- [WP-F8: Model Registry, Trust Layer & Live Red-Team Challenge](docs/WP-F8-Trust-Model-Registry-Red-Team.md)

---

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.

## Acknowledgements

- Google DeepMind Gemma team for open model weights and tool calling capabilities.
- Snowflake for data cloud infrastructure and hackathon sponsorship.
- UCI Machine Learning Repository for the Online Retail dataset.
