"""Export DuckDB demo dataset into a Snowflake SQL script with DDL, batch INSERTs, and role grants."""

from pathlib import Path
import duckdb

def main() -> None:
    db_path = "examples/primary/demo.duckdb"
    out_sql_path = "scripts/setup_snowflake_demo.sql"
    
    conn = duckdb.connect(db_path, read_only=True)
    lines = [
        "-- DataMind Snowflake Data Initialization Script",
        "-- Run this in a Snowflake Worksheet as ACCOUNTADMIN or SYSADMIN",
        "",
        "USE ROLE ACCOUNTADMIN;",
        "USE WAREHOUSE DATAMIND_XS;",
        "USE DATABASE DATAMIND;",
        "USE SCHEMA PUBLIC;",
        "",
        "-- 1. PRODUCTS TABLE",
        "CREATE TABLE IF NOT EXISTS PRODUCTS (",
        "    product_id INTEGER PRIMARY KEY,",
        "    product_name VARCHAR NOT NULL,",
        "    category VARCHAR NOT NULL,",
        "    base_price NUMBER(10, 2) NOT NULL",
        ");",
        "TRUNCATE TABLE PRODUCTS;",
        "",
    ]
    
    # Products data
    prods = conn.execute("SELECT product_id, product_name, category, base_price FROM PRODUCTS").fetchall()
    prod_vals = [f"({p[0]}, '{p[1]}', '{p[2]}', {p[3]})" for p in prods]
    lines.append(f"INSERT INTO PRODUCTS (product_id, product_name, category, base_price) VALUES\n  " + ",\n  ".join(prod_vals) + ";\n")
    
    # 2. SUPPORT_TICKETS table
    lines.extend([
        "-- 2. SUPPORT_TICKETS TABLE",
        "CREATE TABLE IF NOT EXISTS SUPPORT_TICKETS (",
        "    ticket_id VARCHAR PRIMARY KEY,",
        "    created_at DATE NOT NULL,",
        "    product_name VARCHAR NOT NULL,",
        "    category VARCHAR NOT NULL,",
        "    priority VARCHAR NOT NULL,",
        "    body VARCHAR NOT NULL",
        ");",
        "TRUNCATE TABLE SUPPORT_TICKETS;",
        "",
    ])
    tickets = conn.execute("SELECT ticket_id, created_at, product_name, category, priority, body FROM SUPPORT_TICKETS").fetchall()
    ticket_vals = []
    for t in tickets:
        body_esc = t[5].replace("'", "''")
        ticket_vals.append(f"('{t[0]}', '{t[1]}', '{t[2]}', '{t[3]}', '{t[4]}', '{body_esc}')")
    lines.append(f"INSERT INTO SUPPORT_TICKETS (ticket_id, created_at, product_name, category, priority, body) VALUES\n  " + ",\n  ".join(ticket_vals) + ";\n")
    
    # 3. SALES table
    lines.extend([
        "-- 3. SALES TABLE",
        "CREATE TABLE IF NOT EXISTS SALES (",
        "    order_id INTEGER NOT NULL,",
        "    line_no INTEGER NOT NULL,",
        "    order_date DATE NOT NULL,",
        "    order_month DATE NOT NULL,",
        "    product_id INTEGER NOT NULL,",
        "    product_name VARCHAR NOT NULL,",
        "    quantity INTEGER NOT NULL,",
        "    amount NUMBER(12, 2) NOT NULL,",
        "    PRIMARY KEY (order_id, line_no)",
        ");",
        "TRUNCATE TABLE SALES;",
        "",
    ])
    sales = conn.execute("SELECT order_id, line_no, order_date, order_month, product_id, product_name, quantity, amount FROM SALES").fetchall()
    
    # Batch inserts in chunks of 500 rows for clean Snowflake execution
    chunk_size = 500
    for i in range(0, len(sales), chunk_size):
        chunk = sales[i:i+chunk_size]
        vals = [f"({s[0]}, {s[1]}, '{s[2]}', '{s[3]}', {s[4]}, '{s[5]}', {s[6]}, {s[7]})" for s in chunk]
        lines.append(f"INSERT INTO SALES (order_id, line_no, order_date, order_month, product_id, product_name, quantity, amount) VALUES\n  " + ",\n  ".join(vals) + ";\n")
        
    lines.extend([
        "-- 4. GRANT PERMISSIONS TO DATAMIND_READONLY",
        "GRANT USAGE ON WAREHOUSE DATAMIND_XS TO ROLE DATAMIND_READONLY;",
        "GRANT USAGE ON DATABASE DATAMIND TO ROLE DATAMIND_READONLY;",
        "GRANT USAGE ON SCHEMA DATAMIND.PUBLIC TO ROLE DATAMIND_READONLY;",
        "GRANT SELECT ON ALL TABLES IN SCHEMA DATAMIND.PUBLIC TO ROLE DATAMIND_READONLY;",
        "GRANT SELECT ON FUTURE TABLES IN SCHEMA DATAMIND.PUBLIC TO ROLE DATAMIND_READONLY;",
        "",
        "SELECT 'DataMind tables and read-only grants successfully initialized!' AS status;",
    ])
    
    with open(out_sql_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        
    print(f"Generated {out_sql_path} ({len(lines)} lines)")
    conn.close()

if __name__ == "__main__":
    main()
