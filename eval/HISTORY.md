# DataMind Evaluation & Benchmark History

This document reconstructs every evaluation run in DataMind's development trajectory from git history, execution logs, and usage ledgers, in accordance with Section 1 (Authenticity Charter) and Section 2 (WP-F0).

---

## 1. Summary of Runs & Historical Provenance

| Run ID / Timestamp | Git Commit | Suite | Question Set File & SHA-256 | Model | Backend | Score | Pass Rate | Status / Provenance Notes |
|---|---|---|---|---|---|---|---|---|
| **R1**: 2026-10-17T03:39:51 | `bd38891` | `business` (n=12), `trust` (n=3) | `business.yaml` (initial) | `gemma4:e2b` | DuckDB | 15 / 15 | 100.0% | Initial Phase 2 deterministic verifier integration run. |
| **R2**: 2026-10-17T04:10:19 | `61c1f23` | `business` (n=21), `trust` (n=6) | `business.yaml`, `trust.yaml` | `gemma4:e2b` | DuckDB / Snowflake | 27 / 27 | 100.0% | Phase 3 UI integration run; tuned on seen business queries. |
| **R3**: 2026-10-17T13:20:02 | `2888eb7` | `held_out_sealed` (n=10) | `held_out_sealed.yaml` (v1)<br>`0d6f594fabfdac0144f13f8ab4c365675199d2c55525e08e479d8d90da72357f` | `gemma4:e2b` | DuckDB | 6 / 10 | 60.0% | **First run of initial 10-question set**. 4 failures: `S_Q1` (group avg mismatch), `S_Q2` (citation discrepancy), `S_Q4` (no evidence), `S_Q8` (single unit filter). |
| **R4**: 2026-10-17T19:14:34 | `e1fdc5e` | `all` (n=47 total) | `held_out_sealed.yaml` (v2, 20 qs)<br>`40d6cab36ea5858a77df6e5e4dff124cfc38dc755f39eba214c4907a09a68d30` | `gemma4:e2b` | DuckDB | 24 / 25 run<br>(22 not run) | 96.0% (of run) | Halted at question 25 due to default `max_calls_per_run: 50` ceiling. |
| **R5**: 2026-10-17T19:20:03 | `5fc44b2` | `held_out_sealed` (n=20) | `held_out_sealed.yaml` (v2, 20 qs)<br>`40d6cab36ea5858a77df6e5e4dff124cfc38dc755f39eba214c4907a09a68d30` | `gemma4:e2b` | DuckDB | 15 / 20 | 75.0% | **Iterated on a used set, not a generalisation result**. Run after prompt refinements and moving git tag `eval-freeze`. |

---

## 2. Integrity Audit & Honest Disclosures

### A. The Old Sealed Set (`held_out_sealed.yaml`) is USED
- **Authorship:** The 20 questions in `held_out_sealed.yaml` were authored by the coding agent itself, not by an independent human or external party.
- **Iteration History:** The file was first created at commit `2888eb7` (10 questions, score 6/10 = 60.0%). It was subsequently edited, expanded to 20 questions at `e1fdc5e`, and rerun at `5fc44b2` after prompt and call-limit adjustments (scoring 15/20 = 75.0%).
- **Formal Status:** The 15/20 (75.0%) score is **not** a generalisation or clean unseen benchmark figure. It is an **iterated score on a used test set**. It must not be cited as proof of zero-shot model generalisation.
- **Action for WP-F5:** Per the Authenticity Charter, a genuine sealed evaluation requires human-authored questions committed by SHA-256 hash before a frozen commit, executed exactly once on `eval-freeze-v2`.

### B. Git Tag `eval-freeze` Was Moved and Is Untrustworthy
- **Incident Record:** Git tag `eval-freeze` was originally created on commit `e1fdc5e`. After the run on `e1fdc5e` halted due to `max_calls_per_run`, code adjustments were made in commit `5fc44b2`, and the tag was overwritten using `git tag -f eval-freeze`.
- **Audit Decision:** In accordance with the Authenticity Charter ("never force-push, rewrite history, or move tags"), moving the tag violated immutable audit history. The existing tag `eval-freeze` is preserved strictly as historical evidence of this violation and is **not trustworthy**.
- **Remediation:** All future freezes will use distinct, sequential tag names (`eval-freeze-v2`, etc.). No tag will ever be moved again.

### C. Primary Dataset is Synthetic
- **Dataset:** `examples/primary/demo.duckdb` is a **synthetic fixture** (1,450 sales rows, 5 products, 100 support tickets generated with seed 42 in `examples/primary/build_demo_data.py`).
- **Limitation:** In this synthetic dataset, support ticket incidents correlate tightly with product revenue drops, guaranteeing the "why" explanation. Real-world validation requires genuine commercial data.
- **Remediation in WP-F1:** Real public commercial data (Olist Brazilian E-Commerce dataset) will be loaded into Snowflake and DuckDB for authentic multi-table evaluation.

### D. Citation Review Sheet Was Agent-Generated
- `eval/citation_review.csv` was previously populated by the coding agent rather than a human reviewer.
- **Remediation:** The file has been reset to a header-only template for human verification in WP-F5.

### E. Hard-Coded "Structured Query Lane" Removed (2026-10-18)
- **Finding:** The WP-F2 `structured_query_lane` matched the wording of `olist_dev.yaml` questions with keyword rules and returned hand-written Olist SQL without calling the model. The 100% `olist_dev` figure (R6, commit `28edeb1` onward, median latency under 10 ms) therefore did not measure Gemma and does not count as a model result.
- **Action:** The lane, its config flag, its tests and its ablation row were deleted. All runs recorded with `structured_query_lane: true` in `eval/run_ledger.jsonl` and the `olist_dev` 100% claim in older WP reports are superseded; only runs made after this change reflect the model's own SQL generation.

### F. Truncated Answers Traced to Ollama's 4,096-Token Default Context (2026-10-18)
- **Finding:** `Q_MOM_DECLINE` and `Q_MIXED_REVENUE_SUPPORT` failed with `finish_reason=length` at about 4,096 total tokens (prompt plus completion), well under `max_tokens`. Ollama's OpenAI-compatible `/v1` endpoint ignores the per-request `num_ctx` option the client was sending, so the window stayed at the 4,096 default. Gemma 4's default thinking mode made it worse by spending completion tokens, and the length-retry then exceeded `max_tokens_per_call` and crashed the CLI.
- **Action:** Local requests send `reasoning_effort: none` (config `llm.thinking`), the length-retry is clamped to the per-call budget, and `datamind ask` reports budget stops as a clean error. `datamind doctor` now fails when the model has no context window of at least 8,192 configured. The documented fix is a Modelfile variant with `PARAMETER num_ctx 16384` (`gemma4-e2b-16k`).
- **Result after the fix (business suite, three runs):** 20/21, 19/21, 19/21. Truncation failures are gone; remaining failures are model errors (`Q_MONTHLY_REVENUE_TREND` every run, `Q_MIXED_REVENUE_SUPPORT` in two of three). Trust suite: 6/6 in all three runs.

### G. Dev-Set Answers Removed From the System Prompt (2026-10-18)
- **Finding:** `src/datamind/agent/prompts.py` contained the literal answers to dev questions (the Novaship $82,160.45 to $28,357.22 decline of $53,803.23, and an example search query naming Novaship). All earlier `business` results, including the 100% figures, were measured with that leakage.
- **Action:** Replaced with neutral made-up examples. Business suite re-run three times afterwards: 20/21, 20/21, 19/21; trust suite 6/6 each time. The leak was not what the model was relying on for these scores.
- **Failure analysis (no prompt tuning applied):** `Q_MONTHLY_REVENUE_TREND` fails because the model groups by `product_name` and `order_month` for the phrasing "total sales revenue for each month" (15 rows instead of 5), and the verifier reports every number as verified, a verified-but-wrong case. Rephrased as "per month across all products" it answers correctly. `Q_MIXED_REVENUE_SUPPORT` fails intermittently when the model writes an invalid multi-CTE window query, exhausts the 2-repair limit, and falls back to document search only; its answer then says the SQL failed.
- **Remaining dev-set tuning in the prompt:** the schema-specific rules in section 5 (support ticket `priority` vs `category` values, zero-issue catalog pattern, unit-price rule) were written against these questions and are not generalisation evidence.

