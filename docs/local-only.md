# Local-Only & Air-Gapped Mode

DataMind is architected from the ground up to support **100% local, offline, and air-gapped operations**. When running in local mode, zero data, prompts, or credentials ever leave your machine.

---

## What Stays on Your Machine

| Component | Storage / Execution Target | Network Required? |
|---|---|:---:|
| **Language Model (Gemma)** | Local Ollama instance (`http://localhost:11434/v1`) | **None** (100% Localhost) |
| **SQL Engine** | Embedded DuckDB (`demo.duckdb` or `.datamind/uploads/`) | **None** (In-Process C++) |
| **Document Retrieval** | SQLite FTS5 (`.datamind/fts.sqlite`) | **None** (In-Process) |
| **Verification Engine** | Python AST & Deterministic Regex Verifier | **None** (Local CPU) |
| **Charts & Visualizations** | Dependency-free pure SVG generated in browser | **None** (No CDNs) |
| **Telemetry & Analytics** | Disabled by design | **None** |

> [!IMPORTANT]
> **Data Privacy Guarantee:** In local mode, DataMind makes zero outbound internet requests. Your raw database cells, customer support tickets, uploaded CSVs, and model completions never cross the network boundary.

---

## Prerequisites for Local Operation

1. **Ollama:** Installed and running locally:
   ```bash
   ollama serve
   ```
2. **Gemma Model with 16k Context:**
   ```bash
   ollama run gemma4:e2b
   ```
   DataMind automatically passes `{"num_ctx": 16384}` in request options to ensure the full context window is active without requiring manual model re-baking.

---

## Starting DataMind in Local-Only Mode

1. Verify local environment health using the built-in diagnostic doctor:
   ```bash
   datamind doctor
   ```
   All checks will report `[PASS]` for local Ollama, DuckDB, Python, dependencies, and budget guard.

2. Start the interactive Web UI and API server:
   ```bash
   datamind serve --enable-uploads --port 8080
   ```

3. Open your browser to `http://localhost:8080`.

---

## Offline Performance Benchmark (Gemma 4 E2B on Localhost)

Tested on local CPU/GPU with zero cloud latency:
- **Median End-to-End Latency:** 2,264 ms
- **90th Percentile Latency (p90):** 3,459 ms
- **Sealed Benchmark Accuracy:** 75.0% pass rate (15/20 on first attempt)
- **Verifier Mutation Catch Rate:** 100.0% (53/53 mutations detected)
- **False-Positive Rate:** 0.0% on clean text
- **Cloud Spend:** $0.00 USD
