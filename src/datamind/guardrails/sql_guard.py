"""SQL Guardrail enforcing deterministic read-only safety, table whitelisting, CTE alias resolution, and join safety."""

from __future__ import annotations

from typing import Iterable
import sqlglot
from sqlglot import exp


class SQLSecurityError(ValueError):
    """Raised when generated SQL violates safety constraints."""

    def __init__(self, message: str, violation_type: str = "security_violation") -> None:
        super().__init__(message)
        self.message = message
        self.violation_type = violation_type


# Statements that modify state, structure, or permissions
PROHIBITED_NODE_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Command,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.TruncateTable,
    exp.Merge,
    exp.Grant,
    exp.Revoke,
    exp.Kill,
)

# Functions that attempt disk I/O, process execution, or external loading
DANGEROUS_FUNCTIONS = {
    "read_csv",
    "read_csv_auto",
    "read_parquet",
    "read_json",
    "read_json_auto",
    "scan_csv",
    "scan_parquet",
    "copy",
    "system",
    "shell",
    "load",
    "install",
    "eval",
    "import",
    "exec",
}


class SQLGuard:
    """Validates SQL queries against semantic model rules and security invariants."""

    def __init__(
        self,
        approved_tables: Iterable[str],
        dialect: str = "duckdb",
        max_rows: int = 1000,
        enforce_limit: bool = True,
    ) -> None:
        self.approved_tables = {t.strip().lower() for t in approved_tables}
        self.dialect = dialect
        self.max_rows = max_rows
        self.enforce_limit = enforce_limit

    def validate(self, sql: str) -> str:
        """Parse, validate, and return sanitized SQL or raise SQLSecurityError.

        Checks:
        1. Non-empty string.
        2. Exactly one SQL statement.
        3. Root statement is a SELECT or UNION of SELECTs.
        4. No prohibited DDL/DML nodes in the AST.
        5. No dangerous external I/O functions.
        6. Join safety (no CROSS JOIN or joins without ON/USING condition).
        7. Table whitelist (all referenced tables are approved, correctly accounting for CTE aliases).
        """
        trimmed = sql.strip()
        if not trimmed:
            raise SQLSecurityError("Empty SQL query is not allowed", "empty_query")

        # 1. Parse statement
        try:
            statements = sqlglot.parse(trimmed, read=self.dialect)
        except Exception as e:
            raise SQLSecurityError(f"SQL syntax parse error: {e}", "parse_error") from e

        # Filter out empty statements (e.g. trailing semicolons)
        valid_stmts = [s for s in statements if s is not None]
        if not valid_stmts:
            raise SQLSecurityError("No executable SQL statements found", "empty_query")

        # 2. Single statement enforcement
        if len(valid_stmts) > 1:
            raise SQLSecurityError(
                f"Multiple SQL statements detected ({len(valid_stmts)}). Only single statements are permitted.",
                "multiple_statements",
            )

        ast = valid_stmts[0]

        # 3. Whitelist root statement type
        if not isinstance(ast, (exp.Select, exp.Union)):
            raise SQLSecurityError(
                f"Prohibited statement type '{ast.key}'. Only SELECT queries are permitted.",
                "prohibited_statement",
            )

        # 4. Whitelist AST nodes (prohibit DDL/DML anywhere in tree)
        for node in ast.walk():
            if isinstance(node, PROHIBITED_NODE_TYPES):
                raise SQLSecurityError(
                    f"Prohibited AST node type '{node.key}'. Write and DDL operations are forbidden.",
                    "prohibited_node",
                )

        # 5. Check dangerous functions
        for func in ast.find_all(exp.Func):
            fn_key = (func.key or "").strip().lower()
            cls_name = type(func).__name__.lower()
            fn_name = ""
            if hasattr(func, "this") and isinstance(func.this, (exp.Var, exp.Identifier)):
                fn_name = func.this.name.strip().lower()

            is_dangerous = (
                fn_key in DANGEROUS_FUNCTIONS
                or fn_name in DANGEROUS_FUNCTIONS
                or cls_name in DANGEROUS_FUNCTIONS
                or any(d in fn_key or d in cls_name for d in ("readcsv", "readparquet", "readjson"))
            )
            if is_dangerous:
                raise SQLSecurityError(
                    f"Function '{fn_key or cls_name}' is prohibited for security reasons.",
                    "dangerous_function",
                )

        # 6. Join safety
        for join in ast.find_all(exp.Join):
            # Check for CROSS JOIN
            if join.kind and "CROSS" in join.kind.upper():
                raise SQLSecurityError(
                    "CROSS JOIN is prohibited for performance and safety.",
                    "cross_join",
                )
            # Check for unconditional join (Cartesian product)
            has_on = join.args.get("on") is not None
            has_using = join.args.get("using") is not None
            if not has_on and not has_using:
                raise SQLSecurityError(
                    "Unconditional join (Cartesian product) is prohibited. Every JOIN must specify ON or USING.",
                    "unconditional_join",
                )

        # 7. Collect CTE aliases
        cte_aliases: set[str] = set()
        for with_clause in ast.find_all(exp.With):
            for cte in with_clause.expressions:
                if cte.alias:
                    cte_aliases.add(cte.alias.strip().lower())
                elif isinstance(cte.this, exp.Table):
                    cte_aliases.add(cte.this.name.strip().lower())

        # 8. Check all referenced physical tables against whitelist
        for tbl in ast.find_all(exp.Table):
            # If table target is not an identifier (e.g. table-valued function), reject if not approved
            if not isinstance(tbl.this, (exp.Identifier, exp.Var)):
                raise SQLSecurityError(
                    f"Non-standard table reference '{tbl.sql(dialect=self.dialect)}' is prohibited.",
                    "unauthorized_table",
                )

            tbl_name = tbl.name.strip().lower()
            if not tbl_name:
                continue

            # If table is a declared CTE alias, it's valid
            if tbl_name in cte_aliases:
                continue

            # Verify against approved tables
            if tbl_name not in self.approved_tables:
                raise SQLSecurityError(
                    f"Unauthorized table '{tbl.name}'. Allowed tables: {sorted(self.approved_tables)}",
                    "unauthorized_table",
                )

        # Return sanitized SQL
        clean_sql = ast.sql(dialect=self.dialect)
        return clean_sql
