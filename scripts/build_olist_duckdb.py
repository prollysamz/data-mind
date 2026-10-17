"""Build local DuckDB database for Olist Brazilian E-Commerce dataset."""

import pathlib
import time
import duckdb

def build_olist_duckdb(data_dir: str = "data/olist", db_path: str = "data/olist/olist.duckdb") -> None:
    data_path = pathlib.Path(data_dir)
    target_db = pathlib.Path(db_path)
    
    if target_db.exists():
        target_db.unlink()
        
    conn = duckdb.connect(str(target_db))
    print(f"Connecting to DuckDB at: {target_db}")
    start_total = time.perf_counter()
    
    # 8 tables to ingest (skipping geolocation)
    tables = [
        ("olist_customers", "olist_customers_dataset.csv"),
        ("olist_orders", "olist_orders_dataset.csv"),
        ("olist_order_items", "olist_order_items_dataset.csv"),
        ("olist_order_payments", "olist_order_payments_dataset.csv"),
        ("olist_order_reviews", "olist_order_reviews_dataset.csv"),
        ("olist_products", "olist_products_dataset.csv"),
        ("olist_sellers", "olist_sellers_dataset.csv"),
        ("product_category_name_translation", "product_category_name_translation.csv"),
    ]
    
    for tbl_name, csv_file in tables:
        csv_path = data_path / csv_file
        if not csv_path.exists():
            raise FileNotFoundError(f"Missing required CSV: {csv_path}")
        
        t0 = time.perf_counter()
        # Clean column names to prevent BOM or weird chars
        # For product_category_name_translation, strip BOM from product_category_name
        conn.execute(f"""
            CREATE TABLE {tbl_name} AS 
            SELECT * FROM read_csv_auto('{csv_path.as_posix()}', header=True)
        """)
        elapsed = time.perf_counter() - t0
        
        count = conn.execute(f"SELECT COUNT(*) FROM {tbl_name}").fetchone()[0]
        cols = [c[0] for c in conn.execute(f"DESCRIBE {tbl_name}").fetchall()]
        print(f"  [OK] {tbl_name:<35} | {count:>7,} rows | {len(cols):>2} cols | {elapsed:.2f}s")
        
    # Check if translation has BOM column name
    cols = [c[0] for c in conn.execute("DESCRIBE product_category_name_translation").fetchall()]
    if any(c.startswith("\ufeff") for c in cols):
        conn.execute("ALTER TABLE product_category_name_translation RENAME COLUMN \"\ufeffproduct_category_name\" TO product_category_name")
        print("  [Cleaned] Renamed BOM column in product_category_name_translation")

    conn.close()
    total_elapsed = time.perf_counter() - start_total
    print(f"\nSuccessfully built {target_db} in {total_elapsed:.2f}s ({target_db.stat().st_size / (1024*1024):.2f} MB)")

if __name__ == "__main__":
    build_olist_duckdb()
