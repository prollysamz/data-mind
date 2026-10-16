"""Snowflake connectivity and plain SQL check for Gate G0."""

import os
import sys


def main() -> int:
    print("Checking Snowflake credentials from environment...")
    account = os.getenv("SNOWFLAKE_ACCOUNT")
    user = os.getenv("SNOWFLAKE_USER")
    password = os.getenv("SNOWFLAKE_PASSWORD")
    role = os.getenv("SNOWFLAKE_ROLE", "DATAMIND_READONLY")
    warehouse = os.getenv("SNOWFLAKE_WAREHOUSE", "DATAMIND_XS")
    database = os.getenv("SNOWFLAKE_DATABASE")
    schema = os.getenv("SNOWFLAKE_SCHEMA")

    missing = []
    if not account:
        missing.append("SNOWFLAKE_ACCOUNT")
    if not user:
        missing.append("SNOWFLAKE_USER")
    if not password:
        missing.append("SNOWFLAKE_PASSWORD")

    if missing:
        print(f"[UNVERIFIED] Missing required environment variables: {', '.join(missing)}")
        print("Please set them in .env or your environment to verify Snowflake connectivity.")
        return 2

    try:
        import snowflake.connector
    except ImportError:
        print("[FAIL] snowflake-connector-python is not installed. Run `pip install snowflake-connector-python`.")
        return 1

    print(f"Connecting to Snowflake account='{account}', user='{user}', role='{role}', warehouse='{warehouse}'...")
    try:
        conn = snowflake.connector.connect(
            account=account,
            user=user,
            password=password,
            role=role,
            warehouse=warehouse,
            database=database or None,
            schema=schema or None,
        )
        cur = conn.cursor()
        query = "SELECT CURRENT_VERSION(), CURRENT_ROLE(), CURRENT_WAREHOUSE(), CURRENT_DATABASE(), CURRENT_SCHEMA()"
        cur.execute(query)
        row = cur.fetchone()
        query_id = cur.sfqid

        print("\n--- Snowflake Query Execution ---")
        print(f"Query:        {query}")
        print(f"Query ID:     {query_id}")
        if row:
            print(f"Version:      {row[0]}")
            print(f"Role:         {row[1]}")
            print(f"Warehouse:    {row[2]}")
            print(f"Database:     {row[3]}")
            print(f"Schema:       {row[4]}")
        print(">>> [PASS] Snowflake plain SQL query executed successfully.")
        cur.close()
        conn.close()
        return 0
    except Exception as e:
        print(f">>> [FAIL] Snowflake connection or query failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
