"""Build DuckDB database for UCI Online Retail dataset.

Downloads real-world transnational transaction data from the UC Irvine Machine Learning Repository
and builds examples/secondary/online_retail/online_retail.duckdb.
"""

from __future__ import annotations

import contextlib
import csv
import urllib.request
from datetime import datetime
from pathlib import Path

import duckdb

DATASET_URL = "https://raw.githubusercontent.com/guipsamora/pandas_exercises/master/07_Visualization/Online_Retail/Online_Retail.csv"
OUTPUT_DIR = Path(__file__).resolve().parent
DB_PATH = OUTPUT_DIR / "online_retail.duckdb"
BUFFER_BYTES = 2_500_000  # Download ~2.5MB (approx 15,000 real transactions)


def build_database() -> None:
    print(f"Connecting to DuckDB at {DB_PATH}...")
    if DB_PATH.exists():
        with contextlib.suppress(Exception):
            DB_PATH.unlink()

    conn = duckdb.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE ONLINE_RETAIL (
            invoice_no VARCHAR,
            stock_code VARCHAR,
            description VARCHAR,
            quantity INTEGER,
            invoice_date TIMESTAMP,
            unit_price DECIMAL(10, 2),
            customer_id VARCHAR,
            country VARCHAR,
            line_total DECIMAL(12, 2)
        );
    """)

    print(f"Streaming real transactions from {DATASET_URL}...")
    req = urllib.request.Request(DATASET_URL, headers={"User-Agent": "Mozilla/5.0"})

    chunks = []
    total = 0
    with urllib.request.urlopen(req, timeout=15) as response:
        while total < BUFFER_BYTES:
            chunk = response.read(65536)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    raw_bytes = b"".join(chunks)

    text = raw_bytes.decode("latin1")
    lines = text.splitlines()

    # Skip header and last partial line
    reader = csv.reader(lines[1:-1])
    insert_rows = []

    for row in reader:
        if len(row) < 8:
            continue
        inv_no, stock, desc, qty_str, date_str, price_str, cust_id, country = row[:8]
        try:
            qty = int(qty_str)
            price = float(price_str)
            total = round(qty * price, 2)
            if price < 0:
                continue
            iso_date = date_str.strip()
            for fmt in ("%m/%d/%y %H:%M", "%m/%d/%Y %H:%M", "%d-%m-%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(iso_date, fmt)
                    iso_date = dt.strftime("%Y-%m-%d %H:%M:%S")
                    break
                except ValueError:
                    pass

            insert_rows.append((
                inv_no.strip(),
                stock.strip(),
                desc.strip() if desc else None,
                qty,
                iso_date,
                price,
                cust_id.strip() if cust_id else None,
                country.strip(),
                total,
            ))
        except (ValueError, TypeError):
            continue

    temp_csv = OUTPUT_DIR / "temp_import.csv"
    with open(temp_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(insert_rows)

    print(f"Loaded {len(insert_rows)} real UCI Online Retail transactions. Bulk loading into DuckDB...")
    conn.execute(f"COPY ONLINE_RETAIL FROM '{temp_csv.as_posix()}' (AUTO_DETECT FALSE, HEADER FALSE);")
    if temp_csv.exists():
        temp_csv.unlink()

    stats = conn.execute("""
        SELECT
            COUNT(*) as total_rows,
            COUNT(DISTINCT invoice_no) as unique_invoices,
            COUNT(DISTINCT stock_code) as unique_products,
            COUNT(DISTINCT country) as unique_countries,
            SUM(line_total) as total_revenue_gbp
        FROM ONLINE_RETAIL;
    """).fetchone()

    print("UCI Online Retail DuckDB build complete:")
    print(f"  Rows: {stats[0]}")
    print(f"  Invoices: {stats[1]}")
    print(f"  Products: {stats[2]}")
    print(f"  Countries: {stats[3]}")
    print(f"  Total Gross Sales: £{stats[4]:,.2f}")
    conn.close()


if __name__ == "__main__":
    build_database()
