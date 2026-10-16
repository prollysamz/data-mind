# Adding a Database Adapter to DataMind

DataMind uses a clean Protocol-based design to decouple analytical planning and SQL guardrails from the underlying database engine.

All database backends (DuckDB, Snowflake, BigQuery, Postgres) must implement the `DBAdapter` protocol defined in `src/datamind/adapters/base.py`.

---

## 1. The `DBAdapter` Protocol

```python
from dataclasses import dataclass
from typing import Any, Protocol

@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    query_id: str            # e.g., Snowflake sfqid or generated UUID
    elapsed_ms: float
    truncated: bool          # True if row count reached max_rows limit

class DBAdapter(Protocol):
    dialect: str             # "duckdb" | "snowflake" | "postgres" (sqlglot dialect name)

    def execute(self, sql: str) -> QueryResult:
        """Execute a read-only query and return normalized QueryResult."""
        ...

    def explain(self, sql: str) -> dict[str, Any]:
        """Return engine-specific execution plan summary."""
        ...

    def list_tables(self) -> list[str]:
        """List accessible tables in the active schema."""
        ...

    def describe_table(self, table: str) -> list[dict[str, Any]]:
        """Return column metadata: list of dicts with 'name', 'type', 'nullable'."""
        ...

    def sample_rows(self, table: str, n: int = 5) -> QueryResult:
        """Fetch sample rows from table."""
        ...
```

---

## 2. Step-by-Step Implementation

1. **Create Adapter File**:
   Create `src/datamind/adapters/<engine>_adapter.py`.
2. **Implement Read-Only Safety**:
   Ensure connection parameters enforce read-only role or permissions at the driver level (e.g., `read_only=True` in DuckDB, `role="DATAMIND_READONLY"` in Snowflake).
3. **Capture Query ID & Latency**:
   Record the native query ID (such as `cursor.sfqid`) or generate a UUID, and calculate execution time using `time.perf_counter()`.
4. **Detect Row Limit Truncation**:
   Fetch `max_rows + 1` rows to detect whether the user's query exceeded row limit.
5. **Export from Package**:
   Export your adapter class in `src/datamind/adapters/__init__.py`.
6. **Add Unit Tests**:
   Create `tests/test_<engine>_adapter.py` asserting normalized column types, row truncation detection, and read-only behavior.
