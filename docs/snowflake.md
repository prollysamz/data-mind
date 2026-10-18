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

Pick one or both:

- **Synthetic demo tables** (`SALES`, `PRODUCTS`, `SUPPORT_TICKETS`, the same data as `examples/primary/demo.duckdb`): run [`scripts/setup_snowflake_demo.sql`](../scripts/setup_snowflake_demo.sql) in a worksheet.
- **Olist e-commerce data**: download the Olist CSVs from Kaggle into `data/olist/` (see [datasets.md](datasets.md)), then run `python scripts/load_olist_snowflake.py`. Build the local copy too (`python scripts/build_olist_duckdb.py`): review text for document search is indexed from `data/olist/olist.duckdb` (`retrieval.source_duckdb_path` in `datamind_olist_snowflake.yaml`).

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

Export that result (CSV) with the run's output and keep it in the repository, so the evaluation path still works after the trial ends.

## 7. Cost control

- The warehouse auto-suspends after 60 seconds idle; `datamind warehouse-suspend` suspends it immediately.
- The resource monitor suspends it at 5 credits per month.
- DataMind does not call Snowflake Cortex; all model inference is Gemma, outside Snowflake.
