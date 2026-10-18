"""Run 10 control queries across DuckDB and Snowflake on the Olist dataset to verify parity."""

from __future__ import annotations

import decimal
import time

import duckdb

from datamind.adapters.snowflake_adapter import SnowflakeAdapter
from datamind.config import load_config


def normalize_val(val: any) -> any:
    """Normalize numeric types and decimals across DuckDB and Snowflake."""
    if isinstance(val, (int, float)):
        return round(float(val), 2)
    if isinstance(val, decimal.Decimal):
        return round(float(val), 2)
    return str(val) if val is not None else None


def main() -> int:
    duck_conn = duckdb.connect("data/olist/olist.duckdb", read_only=True)

    cfg = load_config("datamind_snowflake.yaml")
    sf_adapter = SnowflakeAdapter(cfg.backend.snowflake, timeout_seconds=30)

    queries = [
        (
            "1. Total orders count",
            "SELECT COUNT(*) FROM olist_orders",
        ),
        (
            "2. Delivered orders count",
            "SELECT COUNT(*) FROM olist_orders WHERE order_status = 'delivered'",
        ),
        (
            "3. Total order line items",
            "SELECT COUNT(*) FROM olist_order_items",
        ),
        (
            "4. Delivered net merchandise revenue",
            "SELECT ROUND(SUM(i.price), 2) FROM olist_order_items i JOIN olist_orders o ON i.order_id = o.order_id WHERE o.order_status = 'delivered'",
        ),
        (
            "5. Delivered freight charges",
            "SELECT ROUND(SUM(i.freight_value), 2) FROM olist_order_items i JOIN olist_orders o ON i.order_id = o.order_id WHERE o.order_status = 'delivered'",
        ),
        (
            "6. Total payments value",
            "SELECT ROUND(SUM(payment_value), 2) FROM olist_order_payments",
        ),
        (
            "7. Average customer review score",
            "SELECT ROUND(AVG(review_score), 4) FROM olist_order_reviews",
        ),
        (
            "8. Total catalog products count",
            "SELECT COUNT(*) FROM olist_products",
        ),
        (
            "9. Total marketplace sellers count",
            "SELECT COUNT(*) FROM olist_sellers",
        ),
        (
            "10. Top 3 categories by item volume",
            """SELECT t.product_category_name_english, COUNT(*) as item_count 
               FROM olist_order_items i 
               JOIN olist_products p ON i.product_id = p.product_id 
               JOIN product_category_name_translation t ON p.product_category_name = t.product_category_name 
               GROUP BY t.product_category_name_english 
               ORDER BY item_count DESC, t.product_category_name_english ASC 
               LIMIT 3""",
        ),
    ]

    print("=" * 80)
    print("OLIST DATASET: DUCKDB VS SNOWFLAKE PARITY VERIFICATION (10 CONTROL QUERIES)")
    print("=" * 80)
    print(f"{'#':<3} {'Control Query Description':<38} {'DuckDB':<18} {'Snowflake':<18} {'Parity'}")
    print("-" * 80)

    all_matched = True
    for desc, sql in queries:
        # 1. Execute on DuckDB
        t0_duck = time.perf_counter()
        duck_rows = duck_conn.execute(sql).fetchall()
        time.perf_counter() - t0_duck

        # 2. Execute on Snowflake
        t0_sf = time.perf_counter()
        sf_res = sf_adapter.execute(sql)
        sf_rows = sf_res.rows
        time.perf_counter() - t0_sf

        norm_duck = [[normalize_val(c) for c in r] for r in duck_rows]
        norm_sf = [[normalize_val(c) for c in r] for r in sf_rows]

        match = (norm_duck == norm_sf)
        parity_str = "[PASS] MATCH" if match else "[FAIL] MISMATCH"
        if not match:
            all_matched = False

        val_duck_str = str(norm_duck[0][0]) if len(norm_duck) == 1 and len(norm_duck[0]) == 1 else f"{len(norm_duck)} rows"
        val_sf_str = str(norm_sf[0][0]) if len(norm_sf) == 1 and len(norm_sf[0]) == 1 else f"{len(norm_sf)} rows"

        print(f"{desc[:41]:<41} | {val_duck_str:<16} | {val_sf_str:<16} | {parity_str}")

    print("-" * 80)
    duck_conn.close()

    # Suspend warehouse after comparison
    try:
        import argparse

        from datamind.cli import handle_warehouse_suspend
        handle_warehouse_suspend(argparse.Namespace(config="datamind_snowflake.yaml"))
    except Exception:
        pass

    if all_matched:
        print("\nVerdict: 10 / 10 CONTROL QUERIES RETURNED IDENTICAL PARITY RESULTS ACROSS DUCKDB AND SNOWFLAKE.")
        return 0
    else:
        print("\nVerdict: DIALECT OR DATA MISMATCH DETECTED.")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
