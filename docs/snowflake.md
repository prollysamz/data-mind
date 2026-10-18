# Running DataMind on Snowflake

Snowflake is the data platform for the hackathon track: the agent's SQL runs in Snowflake at question time, under a read-only role, and every answer carries the Snowflake query ID (`sfqid`) of the queries it is based on. Gemma runs separately (locally through Ollama) and never touches the data directly; it only writes SQL and explains the returned rows.

## 1. Account

Sign up for a free trial at <https://signup.snowflake.com> (email only, no payment details). A trial lasts 30 days or until its credits are used, so create it close to judging or keep the recorded evidence from step 6.

## 2. Bootstrap warehouse, database and roles (once)

Open a worksheet as `ACCOUNTADMIN`, set your login name on the `SET datamind_user = ...` line of [`scripts/snowflake_bootstrap.sql`](../scripts/snowflake_bootstrap.sql), and run the whole script. It is idempotent and creates:

| Object | Purpose |
|---|---|
| `DATAMIND_XS` warehouse | X-Small, auto-suspends after 60 s, starts suspended |
| `DATAMIND_MONITOR` resource monitor | Suspends the warehouse after 5 credits per month |
| `DATAMIND` database, `PUBLIC` schema | Demo and evaluation tables |
| `DATAMIND_LOADER` role | Creates and loads tables |
| `DATAMIND_READONLY` role | `SELECT` only; the agent connects with this role |

Both roles are granted to your user.

## 3. Load data

For browser uploads (CSV/TSV, Parquet, XLSX, JSON/JSONL, PDF, DOCX and text), start with
`datamind serve --enable-uploads`. The loader login needs `DATAMIND_LOADER`; the updated
bootstrap grants that role schema-creation privileges. See [snowflake-first.md](snowflake-first.md)
for separate loader credentials, document extraction limits and failure handling.

Pick one or both:

- **Synthetic demo tables** (`SALES`, `PRODUCTS`, `SUPPORT_TICKETS`, the same data as `examples/primary/demo.duckdb`): run [`scripts/setup_snowflake_demo.sql`](../scripts/setup_snowflake_demo.sql) in a worksheet.
- **Olist e-commerce data**: download the Olist CSVs from Kaggle into `data/olist/` (see [datasets.md](datasets.md)), then run `python scripts/load_olist_snowflake.py`. In Snowflake mode, document search executes SQL against the live text columns and returns query IDs and row citations. A local DuckDB copy is optional for local development and is not used to answer Snowflake questions.

## 4. Credentials

Add to `.env` (git-ignored; never commit it):

```
SNOWFLAKE_ACCOUNT=<account identifier, e.g. abc12345.us-east-1>
SNOWFLAKE_USER=<login name>
SNOWFLAKE_PASSWORD=<password>
```

`SNOWFLAKE_ROLE`, `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_DATABASE` and `SNOWFLAKE_SCHEMA` are optional overrides of the YAML values.

## 5. Check and run

```bash
python scripts/check_snowflake.py                       # connectivity and a plain SELECT
python scripts/test_snowflake_e2e_agent.py              # Gemma question answered in Snowflake, prints query IDs
datamind serve --config datamind_snowflake.yaml --port 8080
datamind eval --suite business --config datamind_snowflake.yaml
python scripts/demo_data_change.py datamind_snowflake.yaml   # answer changes when the data changes
```

`datamind eval` records the backend, the raw answer, the executed SQL and the Snowflake query IDs of every item in `eval/results/`. Ground truth SQL runs in Snowflake too.

## 6. Evidence for judges

Match the query IDs printed above against **Monitoring > Query History** in Snowsight, or:

```sql
SELECT query_id, start_time, role_name, warehouse_name, query_text, rows_produced
FROM TABLE(DATAMIND.INFORMATION_SCHEMA.QUERY_HISTORY_BY_WAREHOUSE(WAREHOUSE_NAME => 'DATAMIND_XS'))
ORDER BY start_time DESC
LIMIT 50;
```

Keep a sanitized run output and query-history export only where dataset terms permit redistribution. For Snowflake sample data, commit the SQL, query IDs and setup instructions; inspect the result rows inside the account instead of copying sample data into the repository. Recorded evidence supports inspection but does not replace a runnable evaluation path after a trial expires. See [judging.md](judging.md) for the required live evaluation procedure.

## 7. Cost control

- The warehouse auto-suspends after 60 seconds idle; `datamind warehouse-suspend` suspends it immediately.
- The resource monitor suspends it at 5 credits per month.
- DataMind does not call Snowflake Cortex; all model inference is Gemma, outside Snowflake.

## 8. Query tags, Time Travel and optional masking

Snowflake connections set `QUERY_TAG` (default `datamind`, configurable under
`backend.snowflake.query_tag`) and a server-side statement timeout. The TPC-H
configuration tags queries `datamind:eval:tpch`. Do not put user questions or secrets
in query tags. [Snowflake parameter reference](https://docs.snowflake.com/en/sql-reference/parameters#query-tag).

Run `python scripts/verify_snowflake_depth.py` to record a tagged query in session
history, a historical read, and loader availability. The saved
[receipt](../eval/evidence/snowflake_depth.json) has live query IDs. Historical reads
use [BEFORE (STATEMENT => ...)](https://docs.snowflake.com/en/sql-reference/constructs/at-before).

`python scripts/demo_data_change.py datamind_snowflake.yaml --output eval/evidence/data_change_snowflake.json` requires the loader
role. It creates a randomly named schema and zero-copy SALES clone, runs the same
Gemma question before and after insertion, compares against live aggregate SQL,
then checks the original value with Time Travel. Cleanup drops only the generated
schema. The prompt exposes only the cloned SALES table and its basic metric definitions;
it supplies no joins, SQL templates or example queries. The writer needs source-table
SELECT and schema creation privileges; readers retain SELECT only. The loader grant
was verified on 2026-10-18. The receipt records PASS only when both agent answers,
the independent aggregate delta and Time Travel agree; failures and missing-role
blockers are saved explicitly, including cleanup status. Exit codes are 0 for a
completed run, 1 for failure, and 2 for a missing-loader blocker.

For a missing-role blocker, an administrator can run
[`scripts/snowflake_enable_ingestion.sql`](../scripts/snowflake_enable_ingestion.sql)
after setting the ingestion login. It grants the loader role, schema creation,
warehouse usage and source SALES read access for cloning. The agent continues to
connect as `DATAMIND_READONLY`. For a separate ingestion login, configure both
`SNOWFLAKE_LOADER_USER` and `SNOWFLAKE_LOADER_PASSWORD`; do not place them in the
semantic model or prompts.

At question time the SQL tool checks direct string equality and IN filters against
live distinct values. A complete domain of at most 25 non-null values permits
validation; domains with 26 or more values, truncated domains, expressions and
derived columns are not exhaustively validated. The pass is bounded to eight
distinct columns per SQL call and does not cache across questions. Unique case or
numeric-code-prefix variants can be resolved and disclosed; ambiguous or unknown
values return a repair/clarification error rather than a confident measured zero.
Validation SQL, Snowflake query IDs and normalization records are exposed separately
from answer query receipts under `validation_queries` in the API and evaluation files.

Quantitative requests must execute structured SQL before document search. Generated
answers with failed numeric/citation verification receive one rewrite attempt. If
the rewrite still fails and the last result is one numeric cell, the answer shows
that exact value and its row citation with a fallback disclosure. This does not
prove that the SQL itself interpreted the question correctly; independent ground
truth evaluation remains necessary.

`scripts/snowflake_governance_demo.sql` is an optional admin-run example on a
fictional contact table in `DATAMIND.GOVERNANCE_DEMO`. It compares admin-visible and
read-only masked values using a Snowflake masking policy. Do not run it against
user data. [Dynamic Data Masking](https://docs.snowflake.com/en/user-guide/security-column-ddm-intro)
requires Enterprise edition. Setup and actual masking remain unverified in this
account; the script's presence is not evidence of deployed governance.

## 9. Schema context and empty-result diagnostics

The model prompt includes declared column descriptions, primary/composite keys,
nullability, units and join relationships, with literal SQL identifiers. For
question-relevant categorical columns, up to three guarded live queries each
collect at most three short examples. These examples are untrusted, incomplete
context, not a complete domain. Names, contact columns and document text are not
sampled by default. The SQL and query IDs appear under `validation_queries`.

An empty result, or an all-NULL aggregate, with a date predicate on one base table
can trigger a separate MIN/MAX and row-count query. Joins, CTEs, subqueries and
set operations are skipped. The diagnostic describes the whole source table with
the original filters excluded; it does not establish which filter caused no
matches. NULL is preserved rather than converted to zero. Its separate row
citation and query ID appear in the UI and `diagnostics` API field. Diagnostic
queries are excluded from answer chart/KPI generation and ground-truth matching.
No configurable warning thresholds are introduced.

Empty results can cite `[[Q1:EXEC]]`: an execution receipt containing SQL, query ID,
returned-row count and truncation status. It opens the corresponding SQL card in
the UI, without inventing `Q1:R1`. Execution citations cannot verify measured
numbers; an empty result is still distinct from a measured zero. If narration
fails verification twice, a single complete empty answer query can use an explicit
execution-status fallback. Truncated results, multiple answer queries and mixed
document evidence do not qualify for that fallback. Empty-result query-lint
warnings remain visible as partial verification.

Run `python scripts/verify_schema_diagnostics.py` for a read-only Snowflake check;
the default output is `eval/evidence/schema_diagnostics_snowflake.json`.
