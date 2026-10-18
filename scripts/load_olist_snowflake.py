"""Automated bulk loader for Olist dataset into Snowflake using DATAMIND_LOADER role.

Loads 8 analytical tables into DATAMIND.PUBLIC via staged COPY INTO.
Skips olist_geolocation_dataset.csv to save warehouse compute.
"""

from __future__ import annotations

import contextlib
import pathlib
import sys
import time

import snowflake.connector

from datamind.config import load_config


def main() -> int:
    config_path = "datamind_snowflake.yaml"
    cfg = load_config(config_path)
    sf_cfg = cfg.backend.snowflake
    if not sf_cfg:
        print("Error: Snowflake configuration missing from datamind_snowflake.yaml", file=sys.stderr)
        return 1

    user = sf_cfg.get_user()
    password = sf_cfg.get_password()
    account = sf_cfg.get_account()

    print("Connecting to Snowflake under loader role 'DATAMIND_LOADER'...")
    try:
        conn = snowflake.connector.connect(
            account=account,
            user=user,
            password=password,
            role="DATAMIND_LOADER",
            warehouse="DATAMIND_XS",
            database="DATAMIND",
            schema="PUBLIC",
            client_session_keep_alive=False,
        )
    except Exception as e:
        print(f"\nConnection Error: {e}")
        print("\nPlease ensure you have executed the DATAMIND_LOADER setup SQL in your Snowflake worksheet.")
        return 1

    cursor = conn.cursor()
    print("Connected successfully. Initializing internal stages and tables...")

    # Table definitions and CSV files
    tables = [
        (
            "OLIST_CUSTOMERS",
            "olist_customers_dataset.csv",
            """(
                CUSTOMER_ID VARCHAR,
                CUSTOMER_UNIQUE_ID VARCHAR,
                CUSTOMER_ZIP_CODE_PREFIX VARCHAR,
                CUSTOMER_CITY VARCHAR,
                CUSTOMER_STATE VARCHAR
            )"""
        ),
        (
            "OLIST_ORDERS",
            "olist_orders_dataset.csv",
            """(
                ORDER_ID VARCHAR,
                CUSTOMER_ID VARCHAR,
                ORDER_STATUS VARCHAR,
                ORDER_PURCHASE_TIMESTAMP TIMESTAMP_NTZ,
                ORDER_APPROVED_AT TIMESTAMP_NTZ,
                ORDER_DELIVERED_CARRIER_DATE TIMESTAMP_NTZ,
                ORDER_DELIVERED_CUSTOMER_DATE TIMESTAMP_NTZ,
                ORDER_ESTIMATED_DELIVERY_DATE TIMESTAMP_NTZ
            )"""
        ),
        (
            "OLIST_ORDER_ITEMS",
            "olist_order_items_dataset.csv",
            """(
                ORDER_ID VARCHAR,
                ORDER_ITEM_ID NUMBER(38,0),
                PRODUCT_ID VARCHAR,
                SELLER_ID VARCHAR,
                SHIPPING_LIMIT_DATE TIMESTAMP_NTZ,
                PRICE FLOAT,
                FREIGHT_VALUE FLOAT
            )"""
        ),
        (
            "OLIST_ORDER_PAYMENTS",
            "olist_order_payments_dataset.csv",
            """(
                ORDER_ID VARCHAR,
                PAYMENT_SEQUENTIAL NUMBER(38,0),
                PAYMENT_TYPE VARCHAR,
                PAYMENT_INSTALLMENTS NUMBER(38,0),
                PAYMENT_VALUE FLOAT
            )"""
        ),
        (
            "OLIST_ORDER_REVIEWS",
            "olist_order_reviews_dataset.csv",
            """(
                REVIEW_ID VARCHAR,
                ORDER_ID VARCHAR,
                REVIEW_SCORE NUMBER(38,0),
                REVIEW_COMMENT_TITLE VARCHAR,
                REVIEW_COMMENT_MESSAGE VARCHAR,
                REVIEW_CREATION_DATE TIMESTAMP_NTZ,
                REVIEW_ANSWER_TIMESTAMP TIMESTAMP_NTZ
            )"""
        ),
        (
            "OLIST_PRODUCTS",
            "olist_products_dataset.csv",
            """(
                PRODUCT_ID VARCHAR,
                PRODUCT_CATEGORY_NAME VARCHAR,
                PRODUCT_NAME_LENGHT NUMBER(38,0),
                PRODUCT_DESCRIPTION_LENGHT NUMBER(38,0),
                PRODUCT_PHOTOS_QTY NUMBER(38,0),
                PRODUCT_WEIGHT_G NUMBER(38,0),
                PRODUCT_LENGTH_CM NUMBER(38,0),
                PRODUCT_HEIGHT_CM NUMBER(38,0),
                PRODUCT_WIDTH_CM NUMBER(38,0)
            )"""
        ),
        (
            "OLIST_SELLERS",
            "olist_sellers_dataset.csv",
            """(
                SELLER_ID VARCHAR,
                SELLER_ZIP_CODE_PREFIX VARCHAR,
                SELLER_CITY VARCHAR,
                SELLER_STATE VARCHAR
            )"""
        ),
        (
            "PRODUCT_CATEGORY_NAME_TRANSLATION",
            "product_category_name_translation.csv",
            """(
                PRODUCT_CATEGORY_NAME VARCHAR,
                PRODUCT_CATEGORY_NAME_ENGLISH VARCHAR
            )"""
        ),
    ]

    data_dir = pathlib.Path("data/olist").resolve()
    print(f"\nStarting staged PUT and COPY for 8 tables from {data_dir}...")
    start_all = time.perf_counter()

    for table_name, csv_filename, columns_sql in tables:
        csv_path = data_dir / csv_filename
        if not csv_path.exists():
            print(f"Skipping {table_name}: {csv_path} not found.")
            continue

        t0 = time.perf_counter()
        print(f"\n--- Loading {table_name} ({csv_filename}) ---")
        
        # Create Table
        cursor.execute(f"CREATE OR REPLACE TABLE {table_name} {columns_sql}")

        # PUT into table stage
        posix_path = str(csv_path).replace("\\", "/")
        put_sql = f"PUT 'file://{posix_path}' @%{table_name} AUTO_COMPRESS=TRUE OVERWRITE=TRUE"
        cursor.execute(put_sql)

        # COPY INTO table
        copy_sql = f"""
            COPY INTO {table_name}
            FROM @%{table_name}
            FILE_FORMAT = (
                TYPE = 'CSV',
                COMPRESSION = 'AUTO',
                FIELD_DELIMITER = ',',
                RECORD_DELIMITER = '\\n',
                SKIP_HEADER = 1,
                FIELD_OPTIONALLY_ENCLOSED_BY = '\"',
                NULL_IF = ('', 'NULL', 'null'),
                EMPTY_FIELD_AS_NULL = TRUE,
                ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE
            )
            ON_ERROR = 'CONTINUE'
        """
        cursor.execute(copy_sql)

        # Verify row count
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        row_count = cursor.fetchone()[0]
        elapsed = time.perf_counter() - t0
        print(f"  [OK] {table_name}: {row_count:,} rows loaded in {elapsed:.2f}s")

    # Grant SELECT on all created tables to DATAMIND_READONLY
    print("\nGranting SELECT on all loaded tables to DATAMIND_READONLY...")
    cursor.execute("GRANT SELECT ON ALL TABLES IN SCHEMA DATAMIND.PUBLIC TO ROLE DATAMIND_READONLY")

    # Clean up stage files
    for table_name, _, _ in tables:
        with contextlib.suppress(Exception):
            cursor.execute(f"REMOVE @%{table_name}")

    # Suspend warehouse to prevent idle compute costs
    print("Suspending DATAMIND_XS warehouse...")
    cursor.execute("ALTER WAREHOUSE DATAMIND_XS SUSPEND")

    total_time = time.perf_counter() - start_all
    cursor.close()
    conn.close()
    print(f"\nAll 8 Olist tables successfully loaded into Snowflake in {total_time:.2f}s! Warehouse suspended.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
