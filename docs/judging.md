# Judging requirements and reproducible evaluation

This document records the supplied judging requirements. It is an acceptance checklist,
not a claim that every gate has passed. DataMind targets PS1. The complete track and
common scoring rubrics were not supplied here; consult the organizer's full brief for
their individual criteria and point allocations.

## Required behavior

- **Sensible handling of ambiguous questions, missing data, empty results and unsupported requests.**
  Ask a focused clarification when a metric, ranking criterion, entity or period is ambiguous.
  Explain missing columns, NULL values and coverage gaps. Distinguish an empty result from
  a measured zero. State the filters used; suggest a supported next step. Refuse writes and
  unsupported operations without inventing data or implying that execution succeeded.
- **Working, reproducible, open-source implementation.** Publish the runnable source,
  an open-source licence, dependency versions, setup commands, data preparation steps,
  configuration examples, model requirements and a feasible evaluation path.

## Question-time evidence and meaningful Snowflake use

Every substantive data answer must be traceable to retrieval or database queries actually
executed in response to that question. Show the executed query or retrieval operation,
result rows or retrieved excerpts, and source references (or equivalent inspectable
provenance). Include the active backend, Snowflake query ID where applicable, filters,
row limits/truncation and citations linking claims to the returned evidence.

For PS1, Snowflake must materially contribute to answering the question. Loading data
into Snowflake and then answering from local files, configuring a connection that is
never queried, or presenting mocked or hard-coded results does not demonstrate meaningful
Snowflake use. A connection check alone is insufficient. Gemma must perform a meaningful
reasoning/generation step; merely listing it as a dependency is insufficient.

Clarification and unsupported-request responses may correctly execute no data query;
they must disclose the limitation and make no unsupported data claims. A successful
query returning no matches is evidence of an empty result, not evidence that the system
failed. A failed query must be reported as an execution failure, not an empty result.

DataMind's SQL tool records SQL, returned rows, elapsed time, truncation and query IDs in
the per-question evidence store. In Snowflake mode, `search_documents` also queries live
database text columns and returns Q row citations. It uses simple keyword OR matching,
with a limit of up to 15 rows per document table; this is not semantic relevance ranking.
DuckDB/SQLite retrieval remains a separate local development option.

## How you will be judged (both tracks)

There are three layers: (1) pass/fail compliance gates, (2) the track rubric, and
(3) the common rubric. **Final score = 0.70 × track score + 0.30 × common score**,
with each score out of 100.

Each observation is scored once. The track rubric owns sponsor-technology depth,
output quality and domain tests (answer correctness, privacy and grounding). The common
rubric owns generic engineering, project hygiene and communication. A failed gate is
not a points deduction: by default the team is not ranked, and no score offsets it.

- **G1 — Open-source repo (both):** Public repository with an open-source licence file.
- **G2 — Reproducible demo (both):** A judge can run the core demo without undisclosed
  credentials or paid services, or a feasible evaluation path is documented.
- **G3 — Real system (both):** The demo shows the real system, not mock-ups or hard-coded outputs.
- **G4 — Data disclosure (both):** Dataset sources and licences are disclosed; no private
  or non-redistributable data is committed.
- **G5 — No secrets (both):** No keys, tokens or passwords in the repository.
- **P1–P3 (PS1):** Snowflake used meaningfully; Gemma used meaningfully; answers derived
  from retrieval or queries run at question time.
- **L1–L4 (PS2):** Gemma used and run locally; no private content leaves the device;
  no systematic fabrication of clauses or citations; not presented as legal advice
  and shows safe escalation.

The PS2 conditions are included for completeness. This PS1 project does not claim PS2
eligibility, and a cloud Snowflake demonstration does not establish PS2 local privacy.

## Judge evaluation path

1. Follow [quickstart.md](quickstart.md) using the published source and pinned
   `requirements.lock`. Install and run Gemma via Ollama; disclose download size, hardware
   and context-window requirements. Local inference requires no paid API key.
2. Generate the clearly labelled synthetic fixture with
   `python examples/primary/build_demo_data.py`. Use DuckDB to inspect the core workflow
   without a Snowflake account. This validates the local path only, not the PS1 Snowflake gate.
3. For PS1, use a judge-controlled Snowflake account/warehouse or a scheduled live session
   using the team's account without sharing credentials. Disclose account requirements,
   warehouse credit consumption and access arrangements before judging. Follow
   [snowflake.md](snowflake.md) for roles, loading, read-only queries and cost controls.
   A recording alone does not guarantee a feasible runnable evaluation path.
4. Run a fresh question, for example:
   `datamind ask "What is total sales revenue?" --config datamind_snowflake.yaml --json`.
   Inspect the evidence SQL, rows and Snowflake query IDs against Snowsight Query History.
   Also ask a document-only question and verify that it issues Snowflake SQL.
5. Exercise an ambiguous request, an absent attribute, an unmatched filter, a NULL aggregate,
   and a prohibited write. Check that clarification, missing data, no matches and query
   errors remain distinguishable. Change a permitted demo row through the loader role,
   repeat the question and verify new query IDs and updated evidence. The provided
   `scripts/demo_data_change.py` automates the numeric example on an isolated clone,
   checks before/after results and Time Travel, and drops only its generated schema.
6. Run automated checks with `python -m pytest`. Unit mocks isolate dependencies and
   are not live-system evidence. Use `scripts/test_snowflake_e2e_agent.py` for an actual
   Gemma/Snowflake question and `datamind eval --suite tpch --config datamind_tpch.yaml`
   for the sample-data evaluation. Do not publish unexecuted suites as passing.
7. Review repository visibility, [LICENSE](../LICENSE), dataset-specific terms in
   [datasets.md](datasets.md), tracked files and the configured secret scanner. An ignored
   `.env` and a scanner configuration alone do not prove the repository or its history is
   free of secrets. Keep private rows and non-redistributable sample data out of evidence commits.

Current automated results and known limitations belong in [eval/HISTORY.md](../eval/HISTORY.md).
Live gate evidence must include the run date, source commit, model, backend and setup;
unit-test success cannot certify a public repository, dataset rights or live cloud execution.
