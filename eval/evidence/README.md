# Evidence files

`snowflake_depth.json` records live query tags in Snowflake session history and a
Time Travel historical read with query IDs. It records the loader blocker at the time
of that run and unverified masking. The loader was subsequently enabled; see the live
mutation receipt below. Live TPC-H results
and their independent SQL receipts are in `eval/results/*tpch_run*.json`; see HISTORY §M.

| File | What it shows | Limits |
|---|---|---|
| `data_change_duckdb.txt` | Earlier DuckDB before/after run. | Does not establish Snowflake behavior. |
| `data_change_snowflake.json` | PASS: local Gemma answers 57493.80 before and 107493.80 after a 50000 insertion into an isolated Snowflake SALES clone; independent SQL, query IDs, Time Travel and cleanup. | Synthetic sales data; explicit sales-line question and SALES-only semantic scope. This is mutation proof, not a general correctness benchmark. |
| `data_change_snowflake_failed_before.json` | Earlier FAIL: loader worked, but Gemma returned an empty answer before insertion; cleanup completed. | Retained failure evidence, not a successful mutation run. |
| `schema_diagnostics_snowflake.json` | PASS: live priority examples, empty 2030 order query, separately cited date coverage (1992-01-01 to 1998-08-02), SQL and query IDs. | No sample records copied. Coverage excludes original filters and does not prove a single cause for the empty result. |
| `snowflake_grants_datamind_readonly.csv` | Snowsight export of `SHOW GRANTS TO ROLE DATAMIND_READONLY` (2026-10-17 23:22 -0700): `USAGE` on database `DATAMIND`, schema `DATAMIND.PUBLIC` and warehouse `DATAMIND_XS`, granted by `ACCOUNTADMIN`. | The export lists only the three `USAGE` grants. It contains no `SELECT` rows, so it does not by itself show which tables the role can read, and no write privileges appear either way. Re-export after loading data (and add `SHOW FUTURE GRANTS IN SCHEMA DATAMIND.PUBLIC`) for the full picture. |

Still missing: a Snowflake Query History export matching the query IDs in `eval/results/2026-10-18_4b77aad_business.json` (see section 6 of `docs/snowflake.md`).

The latest schema-diagnostic receipt also checks that `Q1:EXEC` resolves to the
empty query's execution metadata and that the nonexistent `Q1:R1` is rejected.
This check uses a deterministic status sentence, not an additional model answer.
