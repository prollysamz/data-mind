"""Generate reproducible synthetic sales and support tickets dataset for DataMind demo.

Deterministic seed ensures exact reproducibility across local DuckDB and Snowflake.
"""

from __future__ import annotations

import datetime
from pathlib import Path
import random
import duckdb


def generate_dataset(db_path: str | Path = "examples/primary/demo.duckdb") -> None:
    """Generate reproducible demo dataset with sales and support ticket tables."""
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    if db_file.exists():
        db_file.unlink()

    conn = duckdb.connect(str(db_file))
    rng = random.Random(42)  # Fixed seed for strict determinism

    # 1. PRODUCTS table
    conn.execute("""
        CREATE TABLE PRODUCTS (
            product_id INTEGER PRIMARY KEY,
            product_name VARCHAR NOT NULL,
            category VARCHAR NOT NULL,
            base_price DECIMAL(10, 2) NOT NULL
        );
    """)

    products_data = [
        (101, "Novaship", "Logistics", 120.00),
        (102, "CloudSync", "Infrastructure", 80.00),
        (103, "DataFlow", "Analytics", 150.00),
        (104, "SecureVault", "Security", 200.00),
        (105, "OmniChat", "Communications", 45.00),
    ]
    conn.executemany("INSERT INTO PRODUCTS VALUES (?, ?, ?, ?)", products_data)

    # 2. SALES table (Transactional with MoM trend)
    conn.execute("""
        CREATE TABLE SALES (
            order_id INTEGER NOT NULL,
            line_no INTEGER NOT NULL,
            order_date DATE NOT NULL,
            order_month DATE NOT NULL,
            product_id INTEGER NOT NULL,
            product_name VARCHAR NOT NULL,
            quantity INTEGER NOT NULL,
            amount DECIMAL(12, 2) NOT NULL,
            PRIMARY KEY (order_id, line_no)
        );
    """)

    # We generate data for Jan, Feb, Mar, Apr, May 2026.
    # Deliberate scenario:
    # Novaship has massive revenue in Feb 2026 (~$80,000) and crashes in March 2026 (~$25,000) - largest MoM decline!
    months = [
        (datetime.date(2026, 1, 1), datetime.date(2026, 1, 31)),
        (datetime.date(2026, 2, 1), datetime.date(2026, 2, 28)),
        (datetime.date(2026, 3, 1), datetime.date(2026, 3, 31)),
        (datetime.date(2026, 4, 1), datetime.date(2026, 4, 30)),
        (datetime.date(2026, 5, 1), datetime.date(2026, 5, 31)),
    ]

    sales_rows = []
    order_id = 1000

    # Base monthly targets per product
    product_monthly_targets = {
        "Novaship": {
            datetime.date(2026, 1, 1): 55000,
            datetime.date(2026, 2, 1): 82000,  # Peak
            datetime.date(2026, 3, 1): 28000,  # Large decline: -$54,000
            datetime.date(2026, 4, 1): 32000,
            datetime.date(2026, 5, 1): 35000,
        },
        "CloudSync": {
            datetime.date(2026, 1, 1): 40000,
            datetime.date(2026, 2, 1): 44000,
            datetime.date(2026, 3, 1): 47000,
            datetime.date(2026, 4, 1): 51000,
            datetime.date(2026, 5, 1): 56000,
        },
        "DataFlow": {
            datetime.date(2026, 1, 1): 60000,
            datetime.date(2026, 2, 1): 62000,
            datetime.date(2026, 3, 1): 59000,  # Minor decline: -$3,000
            datetime.date(2026, 4, 1): 64000,
            datetime.date(2026, 5, 1): 67000,
        },
        "SecureVault": {
            datetime.date(2026, 1, 1): 70000,
            datetime.date(2026, 2, 1): 72000,
            datetime.date(2026, 3, 1): 74000,
            datetime.date(2026, 4, 1): 68000,  # Minor decline: -$6,000
            datetime.date(2026, 5, 1): 75000,
        },
        "OmniChat": {
            datetime.date(2026, 1, 1): 25000,
            datetime.date(2026, 2, 1): 28000,
            datetime.date(2026, 3, 1): 27000,  # Minor decline: -$1,000
            datetime.date(2026, 4, 1): 30000,
            datetime.date(2026, 5, 1): 32000,
        },
    }

    prod_id_map = {name: pid for pid, name, _, _ in products_data}

    for start_date, end_date in months:
        month_first_day = start_date
        total_days = (end_date - start_date).days + 1

        for prod_name, targets in product_monthly_targets.items():
            pid = prod_id_map[prod_name]
            target_amount = targets[month_first_day]
            current_amount = 0.0

            while current_amount < target_amount:
                order_id += 1
                day_offset = rng.randint(0, total_days - 1)
                order_date = start_date + datetime.timedelta(days=day_offset)
                qty = rng.randint(1, 15)
                # Compute unit price around base
                unit_price = rng.uniform(80.0, 150.0)
                line_amt = round(qty * unit_price, 2)
                current_amount += line_amt

                sales_rows.append((
                    order_id,
                    1,
                    order_date.isoformat(),
                    month_first_day.isoformat(),
                    pid,
                    prod_name,
                    qty,
                    line_amt,
                ))

    # Fast batch insert in chunks of 500
    chunk_size = 500
    for i in range(0, len(sales_rows), chunk_size):
        chunk = sales_rows[i : i + chunk_size]
        vals = ", ".join(
            f"({r[0]}, {r[1]}, '{r[2]}', '{r[3]}', {r[4]}, '{r[5]}', {r[6]}, {r[7]})"
            for r in chunk
        )
        conn.execute(f"INSERT INTO SALES VALUES {vals}")

    # 3. SUPPORT_TICKETS table (Documents linked to product_name)
    conn.execute("""
        CREATE TABLE SUPPORT_TICKETS (
            ticket_id VARCHAR PRIMARY KEY,
            created_at DATE NOT NULL,
            product_name VARCHAR NOT NULL,
            category VARCHAR NOT NULL,
            priority VARCHAR NOT NULL,
            body VARCHAR NOT NULL
        );
    """)

    tickets_data = [
        # Novaship critical March complaints (explains the March revenue collapse)
        ("TK-1001", "2026-03-02", "Novaship", "Performance", "High",
         "Severe API latency and repeated 504 gateway timeouts during peak dispatch hours. We were unable to print shipping labels for 4 hours."),
        ("TK-1002", "2026-03-05", "Novaship", "Billing", "Urgent",
         "Multiple customers reported duplicate billing charges following the March v2.4 upgrade. Several enterprise clients threatened cancellation."),
        ("TK-1003", "2026-03-12", "Novaship", "Outage", "Critical",
         "Full dashboard outage on March 12 across North America region. Tracking webhooks failed to dispatch events for 8 hours."),
        ("TK-1004", "2026-03-18", "Novaship", "Performance", "High",
         "Database connection pool exhaustion causing batch shipment requests to fail with error code 503."),
        ("TK-1005", "2026-03-24", "Novaship", "Churn", "High",
         "Customer enterprise account Acme Corp downgraded their tier from Enterprise to Starter due to ongoing March downtime and missed SLA."),

        # Other products tickets (routine)
        ("TK-1006", "2026-02-14", "CloudSync", "Feature Request", "Low",
         "Request to add support for custom S3 endpoint configuration in regional sync jobs."),
        ("TK-1007", "2026-03-10", "CloudSync", "Usability", "Medium",
         "Minor delay in desktop sync client tray icon status refresh after waking laptop from sleep."),
        ("TK-1008", "2026-03-15", "DataFlow", "Performance", "Medium",
         "Query execution time on 50GB dataset is slightly slower than expected on standard tier."),
        ("TK-1009", "2026-04-05", "SecureVault", "Integration", "Low",
         "Documentation request for Okta SAML SSO attribute mapping guidelines."),
        ("TK-1010", "2026-03-20", "OmniChat", "Bug", "Medium",
         "Emoji reaction picker occasionally flickers when scrolling through reaction history."),
    ]

    conn.executemany("INSERT INTO SUPPORT_TICKETS VALUES (?, ?, ?, ?, ?, ?)", tickets_data)
    conn.commit()
    conn.close()
    print(f"Dataset successfully generated at {db_path} ({len(sales_rows)} sales lines, {len(tickets_data)} tickets)", flush=True)


if __name__ == "__main__":
    generate_dataset()
