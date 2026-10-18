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

### H. Report Corrections and Citation Sheet Reset (2026-10-18)
- `eval/citation_review.csv` held 40 rows marked as human-verified, but several values were malformed (currency digits missing) and the last three cited `policy.md`, `sla.md` and `compliance.md`, which do not exist. It was not a human audit and has been reset to a header-only template. No human citation audit exists yet.
- WP-F5 quoted a sealed-set digest (`2e604f76...`) that matches no file; the committed digest `40d6cab3...` in `sealed_commitment.txt` matches `held_out_sealed.yaml` as stored in git (LF line endings; a Windows CRLF checkout hashes differently).
- WP reports F2-F7 carry dated correction notes; "Completed & Certified" was changed to "Completed (self-reported)".

### I. Runs After the Grain Check and Server Lock (2026-10-18)
- Business suite, commit `f74f3d0`: 20/21 (`Q_MONTHLY_REVENUE_TREND` failed); trust 6/6. Results now store each item's answer, executed SQL and query IDs.
- One earlier run on commit `cc47ea5` scored business 21/21 and trust 6/6. Its result files were discarded because the trust file was wrongly labelled `-dirty` (fixed in the same session); it is mentioned here so the range quoted in the README (19-21 of 21 over five runs) is complete.


### J. Phrase-List Refusal/Clarification Lanes Replaced (2026-10-18)
- **Finding:** `_check_unanswerable` and `_is_ambiguous` in the orchestrator decided refusals and clarifications from phrase lists written for the dev questions (e.g. "profit margin", "gps coordinates", "top products", "what was our revenue in 2017"), and returned canned Olist-specific refusal texts.
- **Action:** Replaced by `agent/answerability.py`, which matches the question against the semantic model's vocabulary and asks the orchestrator model for a JSON verdict only when that is inconclusive. Trust suite on commit `3a4fac1`: 6/6.
- **Expected effect on `olist_dev`:** the four ambiguous items ("What were our top products?", "What was our revenue in 2017?", "Who are the best sellers?", "How did sales perform recently?") passed only through the phrase list; they name schema attributes, so they now go to the SQL agent and are likely to fail the clarification check. Olist dev scores before this commit are not comparable.

### K. Business Suite on Live Snowflake (2026-10-18)
- Business suite against Snowflake (`DATAMIND.PUBLIC`, `DATAMIND_XS`, role `DATAMIND_READONLY`, connecting as a `LEGACY_SERVICE` user), commit `4b77aad`, model `gemma4-e2b-16k`: 20/21; `Q_MONTHLY_REVENUE_TREND` failed (same product-grain failure as in section G). All 21 items carry their Snowflake query IDs in `eval/results/2026-10-18_4b77aad_business.json`.
- Query History export from Snowsight (section 6 of `docs/snowflake.md`) has not been added yet.

### L. Structured Lane Restored (Schema-Driven) and TPC-H Reusability Suite Added (2026-10-18)
- **Context:** The hard-coded `structured_query_lane` removed in section E matched the wording of `olist_dev.yaml` questions and returned hand-written Olist SQL. A parallel fork of this repository (`DARK-1926/MAD-2-LABS`, commit `bf99164`) kept the lane but rewrote it to compile from the semantic model instead of hard-coded strings. That approach is sound, so the lane has been reinstated here in a stricter form rather than left deleted.
- **What the lane now does:** `try_structured_lane` matches a question against the metrics the *active* semantic model declares, and returns that metric's own SQL. It contains no table names, column names or literals of its own, so pointing DataMind at another schema changes what it can answer. It refuses any question containing a breakdown, ranking, comparison or subset term, any digit or quoted string, any all-caps code, any mid-sentence capitalised word, and any question matching two metrics at once. On no match it returns `None` and the question goes to the model.
- **Difference from the fork's version:** the fork's lane also renders the answer deterministically, bypassing the model entirely. Here the lane supplies only the SQL; Gemma still narrates the rows, and the answer is cited and verified on the normal path. The fork's version also hard-codes Brazilian state codes (`sp|rj|mg|...`) as a disqualifier; the check here is "any all-caps token", which is schema-independent.
- **Still off by default** (`agent.structured_query_lane: false`). Any run recorded with it enabled measures the semantic model's SQL, not Gemma's SQL generation, and must say so. No benchmark figure in this repository was produced with the lane enabled.
- **Sibling fan-out check added:** `QueryLinter` already flagged aggregates over a single 1-to-many join without `DISTINCT`. It did not flag joining one parent to *two* of its child tables at once, where the children's rows multiply together and every aggregate over them is inflated. That case is now `sibling_fan_out`, derived from `semantic_model.one_to_many_joins()`. The fork ships an equivalent `join_fanout_guard.py`, but it hard-codes Olist table names and is never imported anywhere in that repository.
- **TPC-H suite (`eval/questions/tpch.yaml`, 10 questions):** runs against `SNOWFLAKE_SAMPLE_DATA.TPCH_SF1`, which is shared into every Snowflake account, so it needs no download or load step. The semantic model (`examples/tpch/semantic_model.yaml`) was generated by introspection, and no question, table or column in it appears in DataMind's code or prompts. Every question carries `ground_truth_sql`, which the runner executes against the same database, so a pass means the agent's SQL reproduced the live answer rather than matching a committed number.
- **Status at that revision:** not yet run. Superseded by section M below. The fork's README reported 90.0% (9/10) on a different script and question set; that was not a result from this suite.

### M. Live TPC-H baseline, schema review, and Snowflake-depth checks (2026-10-18)

Both runs used `datamind eval --suite tpch --config datamind_tpch.yaml --no-cache`,
local `gemma4-e2b-16k` and real `SNOWFLAKE_SAMPLE_DATA.TPCH_SF1` queries.
The tree was dirty (`50e54a6-dirty`), so results do not identify a clean committed build.

- Initial baseline: **3/10**, [run_20261018_1792327134](results/2026-10-18_50e54a6-dirty_tpch_run_20261018_1792327134.json).
- After reviewing semantic descriptions/foreign keys and fixing generic pruning to tokenize plural names and underscored identifiers: **8/10**, [run_20261018_1792327250](results/2026-10-18_50e54a6-dirty_tpch_run_20261018_1792327250.json).
- No questions, expected values or gold SQL were added to the agent. Because changes followed the initial results, the second run is a development evaluation, not a held-out generalization result.
- The priority question failed: the model queried `'Urgent'` rather than `'1-URGENT'` and returned a misleading zero. The yearly aggregation failed by choosing document search. Neither is a pass, despite numeric citations being internally consistent.
- Before running either suite, the comparator was tightened: compare every cell, all rows and duplicate multiplicities at numeric precision 0.01; no partial-column, extra-row or empty-ground-truth automatic passes; reject truncation. Query ordering is checked only when `ordered: true` is set on an item. The suite currently compares unordered complete results.
- Gold SQL executes after the agent response; reports preserve both query IDs, expected derived results, executed SQL and result counts. Original benchmark records retrieved by a mistaken document search are omitted from saved reports. No raw sample dataset is committed.
- Separate SQL authored in this repository is not external authorship. Competitor suites differ in questions, model sizes, evaluation methods and caching, so these percentages are not directly comparable.
- Query tags and server-side statement timeouts are now set on real Snowflake connections. The [depth receipt](evidence/snowflake_depth.json) confirms the tag in session query history and a historical read via `BEFORE (STATEMENT => ...)`.
- A read-only historical read is not a mutation demo. The existing ingestion login still cannot assume `DATAMIND_LOADER` (390186). The updated data-change script uses an isolated zero-copy SALES clone and verifies before/after agent results and Time Travel; its mutation path remains **not run**.
- Optional [masking setup](../scripts/snowflake_governance_demo.sql) uses a fictional contact in a dedicated schema. It requires admin setup and Enterprise edition; deployment and masked/unmasked comparison remain **not verified**.

Repository comparison checked on 2026-10-18:
[Dextro](https://github.com/ZERODAY-2026/Dextro/tree/0575b9ca0c9a90c9d9c7cc1b670c00f8013a0809),
[Ctrl-Z](https://github.com/ZERODAY-2026/Ctrl-Z/tree/6d9b8cd47672b2b8c229487462c8cd74e17ec226),
[ONLYFUNC](https://github.com/ZERODAY-2026/ONLYFUNC/tree/16d8790f95fe1757929ac115cfcbe718d1b89941).
All three publish live evaluation reports with ground-truth comparisons. Dextro also
documents masking, query tags and a Time Travel mutation script. Ctrl-Z explicitly
marks its mutation demo unverified. This inspection confirms published code/reports,
not independent execution in the other teams' Snowflake accounts; no claim that only
one repository in the entire organization supports Time Travel has been established.

### N. Live filter validation, SQL routing and scalar narration repair (2026-10-18)

The original priority-code and yearly-aggregation failures are now fixed in the
latest live run, with no gold SQL added to prompts or runtime lookup tables.
All follow-up runs use the same ten questions, local `gemma4-e2b-16k`, Snowflake
TPC-H SF1, and `--no-cache`:

- [7/10, run_1792327807](results/2026-10-18_50e54a6-dirty_tpch_run_20261018_1792327807.json): added bounded live categorical validation and SQL-first routing. Invalid `'Urgent'` was correctly rejected, but Gemma failed to repair it. Yearly SQL still hit function errors; discounted-revenue narration introduced a wrong magnitude.
- [9/10, run_1792327915](results/2026-10-18_50e54a6-dirty_tpch_run_20261018_1792327915.json): unique live category normalization resolves case/numeric-prefix variants, while ambiguous matches require clarification. SQL repair hints now name the dialect and native date expressions. Both original failures pass; the wrong scalar narration remains caught.
- [10/10, run_1792327991](results/2026-10-18_50e54a6-dirty_tpch_run_20261018_1792327991.json): one verification-driven narration rewrite, followed by an exact single-cell receipt when the rewrite still fails. Discounted revenue uses this disclosed fallback. This is not ten flawless model narrations: SQL outputs match independently authored live SQL, and final numerical claims pass verification.

Category discovery is executed at question time and recorded under
`validation_queries`, separately from answer queries. It checks direct string
equality/IN predicates on base-table columns only. More than 25 distinct values or
truncation makes the domain inconclusive; at most eight domains are checked per
SQL call. No fuzzy synonym substitutions or domain-specific query templates are
used. API responses expose validation receipts and normalization mappings.

Regression tests cover normalization, ambiguous codes, unmatched IN values,
incomplete domains, real measured zeros, blocked document search for numerical
requests, and failed narration falling back to the exact scalar. A retry that
drops all citations cannot turn a rejected answer into a verified "Done" response.

Snowflake permissions were rechecked: the loader role still fails with 390186.
The isolated mutation demo and masking deployment remain blocked/unverified.
An administrator can use [snowflake_enable_ingestion.sql](../scripts/snowflake_enable_ingestion.sql)
for the narrow ingestion grants, then run the mutation script. The agent remains
read-only. No admin credentials were available or granted during this work.

Final offline verification: **371 tests passed**, with Ruff clean. The application
was restarted on port 8081. A separate HTTP smoke check against the synthetic
CloudSync question returned empty model output; this exposed an existing empty
answer being labelled successful. A bounded retry and explicit
`empty_model_response` failure now prevent blank verified answers. The HTTP recheck
confirmed `success: false` and an actionable message. This smoke question has not
been demonstrated as a successful answer in this run; the 10/10 claim applies only
to the recorded TPC-H development suite, not all schemas or UI questions.
