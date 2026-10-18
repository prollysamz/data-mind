# Snowflake-first uploads, Gemma and Bedrock Mantle

`datamind serve`, `datamind ask` and `datamind mcp` now default to
`datamind_snowflake.yaml`. The local development configuration remains available with
`--config datamind.yaml`. Failure to connect to Snowflake never selects DuckDB instead.
Both structured questions and document searches execute SQL in Snowflake at question time.

## Setup and roles

Install with `python -m pip install -e ".[dev,snowflake,uploads]"`, or use
`requirements.lock` for the tested versions. Follow [snowflake.md](snowflake.md) and run
the updated [bootstrap SQL](../scripts/snowflake_bootstrap.sql) as an administrator.
In addition to the existing privileges, the loader needs `CREATE SCHEMA` on `DATAMIND`.

The agent connects as `DATAMIND_READONLY` with secondary roles disabled. Only the ingestion
service uses `DATAMIND_LOADER` for creating, inserting and deleting uploaded tables. This
connection is never offered as an agent tool. Ingestion uses bound insert values and
checks the resulting row count before reporting success.

Two credential arrangements are supported:

- A Snowflake login holding both roles, with separate connections selecting each role.
- A read-only agent login in `SNOWFLAKE_USER` / `SNOWFLAKE_PASSWORD` and a separate ingestion
  login in `SNOWFLAKE_LOADER_USER` / `SNOWFLAKE_LOADER_PASSWORD`. Set both loader variables
  together. Grant the ingestion login `DATAMIND_LOADER`; do not give the agent write privileges.

Account administrators can use the bootstrap to create the roles, then grant the loader
role to the ingestion login. A login restricted to `DATAMIND_READONLY` cannot provision
these privileges. The administrator must make that grant; the application does not elevate
the read-only connection or fall back to local storage.

Start the app:

```bash
datamind serve --enable-uploads --port 8080
```

## Upload lifecycle

Add data → validate/extract → transient parsing/profiling → insert into Snowflake →
verify row count → review enabled columns → activate → ask → inspect SQL and query IDs.

Each session owns `DATAMIND.DATAMIND_UPLOAD_<random session ID>`. Database tables and
columns use uppercase identifiers. In Snowflake mode, parsing uses an in-memory DuckDB
connection, not a persistent local database. Temporary input files are removed after
ingestion. Questions read the Snowflake tables, including document text. Local session
metadata includes profiles and small previews, and browser conversations contain displayed
answers/evidence; this is not a claim that no data exists on the device.

Upload or row-count verification failure leaves the dataset inactive. The agent cannot
query an older local upload while operating in Snowflake mode; re-upload it to Snowflake.
Deletion drops only the session's generated schema. If cloud deletion fails, metadata is
retained so cleanup can be retried. Expired sessions are cleaned up on startup or during
session creation; shutdown cleans uploads unless `--keep-uploads` is used. Cleanup is not
a continuously running TTL service. Check for retained sessions after network failures.

## Supported formats and boundaries

- **CSV, TSV, Parquet:** tabular ingestion, type inference and column review.
- **XLSX:** one worksheet per file; uses saved cell values. Formulas/macros are never
  executed, and missing cached formula results can appear blank. Export extra sheets separately.
- **JSON, JSONL, NDJSON:** an array of records or one object per line. Nested values
  are retained as JSON strings; this is not automatic relational flattening.
- **PDF:** extracted text, with page references. Encrypted and image-only PDFs are rejected;
  run OCR separately for scans. No PDF scripts or embedded attachments are executed.
- **DOCX:** body/table paragraph text with paragraph references. Headers, images and embedded
  objects are not interpreted. Legacy `.doc` and macro-enabled formats are unsupported.
- **TXT, Markdown:** UTF-8 text split into bounded chunks, preserving source filename.

Document rows retain `source_name`, `source_location`, `chunk_id` and `body`, so SQL row
citations can be inspected against the source location. Limits include 50 MB per input,
200 columns, two million rows, 500 PDF pages, five million extracted text characters,
and 100 MB expanded Office/conversion data. These are resource bounds, not a malware
scanning or sandboxing guarantee. Snowflake search uses bounded keyword matching, not
embeddings or semantic relevance ranking.

## Bedrock Mantle in Settings

Choose **Amazon Bedrock Mantle**, enter the Bedrock API key, AWS bearer token, and Bedrock base URL, select
the route, then **Load models**, choose a Gemma model and save. Discovery lists Gemma
models reported by the real Mantle catalogue. Test provider sends a small real request.
Settings reads never return the full key. Keys are stored in a local gitignored JSON
file in plaintext; environment variables avoid persisting a key through the UI.

Environment alternatives:

```dotenv
BEDROCK_API_KEY=<Amazon Bedrock API key>
AWS_BEARER_TOKEN_BEDROCK=<AWS bearer token>
BEDROCK_BASE_URL=https://bedrock-mantle.us-east-1.api.aws/openai/v1
AWS_REGION=us-east-1
BEDROCK_MODEL=google.gemma-4-26b-a4b
BEDROCK_MANTLE_ROUTE=/openai/v1
```

Selecting Bedrock in Settings is still required. AWS access-key/secret-key pairs and
SigV4 are not implemented by this provider. Mantle routes vary by model; use `/v1` or
`/openai/v1` as documented for the selected model. See the
[AWS Chat Completions documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions.html)
and [AWS Gemma documentation](https://aws.amazon.com/blogs/machine-learning/introducing-gemma-4-models-on-amazon-bedrock/).
The endpoint hostname is derived from a validated AWS region, not a user-supplied URL.

Inference and Snowflake compute can incur separate charges. Token/call limits apply.
For a financial ceiling, configure `DATAMIND_BUDGET_MAX_USD`, `DATAMIND_PRICE_INPUT_M`
and `DATAMIND_PRICE_OUTPUT_M` using the selected model's current official prices.
Without price inputs, a configured USD cap fails closed; without a cap, token counts
are recorded but a zero calculated cost does not mean AWS inference was free.

## Charts, KPIs and security

The API exposes visualizations for all suitable executed query results. The UI can switch
between them, shows multiple KPIs from a single result, renders up to four time series,
preserves missing values as gaps, sorts dates and links points/KPIs to evidence rows.
SVG export is available. Repeated category/time labels fall back to a table when a single
series would misrepresent grouping. Charts do not invent totals, percentage changes or
zeroes for missing observations. Truncated database results are labelled.

Results with one row per category per date can also form up to four separate lines.
Each series point retains the source row for that category/date; duplicate observations
for the same pair require explicit SQL aggregation rather than silent chart-side summing.

SQL guards reject writes, unsafe functions, unapproved tables and CTE scope tricks.
For uploads, enabled columns form an enforced query schema; wildcard queries expand to
those columns, and disabled columns cannot be queried. The HTTP API rejects cross-origin
writes and requires JSON. Explicit credential-exfiltration/instruction-override patterns
are refused; retrieved content is marked as untrusted data. These heuristic prompt
checks can miss attacks and can over-refuse: read-only database permissions and SQL
validation remain the execution boundary. This loopback app is not a production
multi-tenant authentication service.

Unknown UDFs and namespaced functions are rejected to prevent a read-only `SELECT`
from invoking an unapproved external service. Extending the allowed dialect functions
requires a code change and review; a prompt cannot expand this allowlist.

## Verification status

Automated tests use real local parsers/databases plus mocked cloud boundaries; they are
not live AWS or Snowflake upload receipts. On 2026-10-18, live Snowflake reads succeeded
with the configured `DATAMIND_READONLY` login. Its available roles did not include
`DATAMIND_LOADER`, so live upload verification stopped at loader login. No local fallback
was activated. An administrator must grant/configure the loader before a complete live
upload → question → deletion run can be certified. No Bedrock key was configured during
this implementation, so live Mantle inference remains to be verified after key setup.

The browser was also exercised with local `gemma4-e2b-16k` against Snowflake: a two-metric
sales question returned verified revenue/quantity KPIs with SQL and a query ID, and a
document-only support question returned verbatim ticket text with five SQL row citations.
This demonstrates question-time Snowflake use; it does not certify the blocked upload path.

After granting the loader role, run the opt-in live smoke test:

```bash
python scripts/verify_snowflake_upload.py --config datamind_snowflake.yaml
```

It loads two clearly synthetic rows, asks Gemma against the real Snowflake table,
prints the evidence and deletes its own session schema. It uses warehouse credits and
is deliberately excluded from automated unit tests.
