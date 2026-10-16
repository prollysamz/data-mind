import os
from datamind.config import load_dotenv, load_config
from datamind.adapters.snowflake_adapter import SnowflakeAdapter
from datamind.guardrails.sql_guard import SQLGuard
from datamind.agent.orchestrator import AgentOrchestrator
from datamind.llm.client import LLMClient
from datamind.retrieval.sqlite_fts import SQLiteFTSRetriever
from datamind.semantic.model import SemanticModel, TableDef, ColumnDef

load_dotenv(".env")
config = load_config("datamind.yaml")

# Define semantic model for Snowflake READONLY_TEST
model = SemanticModel(
    name="snowflake_test_db",
    description="Snowflake validation database with verified read-only tables.",
    default_currency="USD",
    currency_symbol="$",
    tables=[
        TableDef(
            name="READONLY_TEST",
            description="Verified read-only validation table in Snowflake containing test rows.",
            columns=[
                ColumnDef(name="id", type="INTEGER", description="Row identifier", is_primary_key=True),
                ColumnDef(name="note", type="VARCHAR", description="Text note associated with row"),
            ]
        )
    ]
)

adapter = SnowflakeAdapter(
    account=os.getenv("SNOWFLAKE_ACCOUNT"),
    user=os.getenv("SNOWFLAKE_USER"),
    password=os.getenv("SNOWFLAKE_PASSWORD"),
    role="DATAMIND_READONLY",
    warehouse="DATAMIND_XS",
    database="DATAMIND",
    schema="PUBLIC",
)

retriever = SQLiteFTSRetriever(index_path=".datamind/fts_sf.sqlite")
llm_client = LLMClient(config.llm)

orchestrator = AgentOrchestrator(
    llm_client=llm_client,
    db_adapter=adapter,
    retriever=retriever,
    semantic_model=model,
    sql_guard=SQLGuard(approved_tables=["READONLY_TEST"], dialect="snowflake"),
)

question = "What rows and notes are in the READONLY_TEST table?"
print(f"Running Snowflake End-to-End Agent Question: '{question}'...")
result = orchestrator.run(question)

print("\n" + "="*50)
print("AGENT ANSWER:")
print(result.answer)
print("="*50)
print(f"Success: {result.success}")
print(f"Clean citations: {result.citation_report.is_clean}")
print(f"Valid citations: {result.citation_report.valid_count}")
print(f"Invalid citations: {result.citation_report.invalid_count}")
print(f"Verified numbers: {result.citation_report.verified_numbers_count}")
print(f"Discrepancies: {result.citation_report.discrepancy_count}")

for q in result.evidence_store.queries:
    print(f"\nSnowflake Query ID: {q.result.query_id}")
    print(f"Elapsed: {q.result.elapsed_ms}ms")
    print(f"SQL: {q.sql}")
    print(f"Rows ({len(q.result.rows)}): {q.result.rows}")

adapter.close()
retriever.close()
