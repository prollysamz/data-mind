# Evidence files

| File | What it shows | Limits |
|---|---|---|
| `data_change_duckdb.txt` | `scripts/demo_data_change.py` on DuckDB: the same question answered before and after a data change, with query IDs. | DuckDB only; no Snowflake run of the data-change demo is recorded yet. |
| `snowflake_grants_datamind_readonly.csv` | Snowsight export of `SHOW GRANTS TO ROLE DATAMIND_READONLY` (2026-10-17 23:22 -0700): `USAGE` on database `DATAMIND`, schema `DATAMIND.PUBLIC` and warehouse `DATAMIND_XS`, granted by `ACCOUNTADMIN`. | The export lists only the three `USAGE` grants. It contains no `SELECT` rows, so it does not by itself show which tables the role can read, and no write privileges appear either way. Re-export after loading data (and add `SHOW FUTURE GRANTS IN SCHEMA DATAMIND.PUBLIC`) for the full picture. |

Still missing: a Snowflake Query History export matching the query IDs in `eval/results/2026-10-18_4b77aad_business.json` (see section 6 of `docs/snowflake.md`).
