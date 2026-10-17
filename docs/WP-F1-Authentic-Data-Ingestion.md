# WP-F1 Report: Authentic Real Data Ingestion (Olist E-Commerce)

**Work Package:** WP-F1  
**Status:** Completed & Certified  
**Key Commit:** `c8cbd68`  
**Dataset:** Brazilian E-Commerce Public Dataset by Olist (Kaggle)  
**Artifacts:** [`examples/olist/semantic_model.yaml`](file:///d:/HackOctober/examples/olist/semantic_model.yaml), [`examples/olist/build_olist_duckdb.py`](file:///d:/HackOctober/examples/olist/build_olist_duckdb.py)

---

## 1. Executive Summary & Purpose

To move beyond small synthetic fixtures, WP-F1 ingested the full, authentic **Olist Brazilian E-Commerce public dataset** (100,000 real customer orders, 3,000+ sellers, 70+ product categories, payments, delivery timestamps, and customer reviews).

The dataset was ingested into both **local DuckDB** and **remote Snowflake** with full schema parity and a complete semantic data model.

---

## 2. Ingested Tables & Volume

| Table Name | Description | Approximate Row Count |
| :--- | :--- | :--- |
| `olist_orders` | Order life cycle, delivery timestamps, and status | 99,441 rows |
| `olist_order_items` | Line items with price and freight value | 112,650 rows |
| `olist_products` | Product categories, weight, dimensions, photo counts | 32,951 rows |
| `olist_sellers` | Merchant identifiers and zip code prefixes | 3,095 rows |
| `olist_customers` | Customer city, state, and geographic location | 99,441 rows |
| `olist_order_payments` | Payment type (credit card, boleto, voucher) & installments | 103,886 rows |
| `olist_order_reviews` | Review scores (1 to 5 stars) and verbatim Portuguese comment text | 99,224 rows |
| `product_category_name_translation` | Portuguese to English category mappings | 71 rows |
| `olist_geolocation` | Zip code coordinates and geographic boundaries | 1,000,163 rows |

---

## 3. Implementation Details

### 3.1 Dual-Backend Parity (DuckDB & Snowflake)
* **DuckDB Storage:** Compact, fast column-store at `data/olist/olist.duckdb` (indexed with primary/foreign keys).
* **Snowflake Schema:** Tables created in `DATAMIND.PUBLIC` warehouse `DATAMIND_XS` under read-only role `DATAMIND_READONLY`.
* **Cross-Dialect Normalization:** Automated dialect adapter handling timestamp truncation (`DATE_TRUNC('month', order_purchase_timestamp)`), string quoting, and null handling.

### 3.2 Semantic Model Specification
Authored [`examples/olist/semantic_model.yaml`](file:///d:/HackOctober/examples/olist/semantic_model.yaml) defining:
* Primary keys and foreign key join graph (`orders -> order_items -> products`, etc.).
* Standard metric formulas (Gross Merchandise Value `GMV = SUM(price)`, Freight Margin, Average Order Value).
* Default currency specified as Brazilian Real (`BRL`, symbol `R$`).
* Verified join paths preventing Cartesian fan-out bugs.

---

## 4. Key Verification Metrics
* **Parity Test:** All 9 tables introspected and verified across DuckDB and Snowflake.
* **Dialect Compatibility:** Verified identical aggregation outputs on `SELECT SUM(price) FROM olist_order_items` (R$ 13,591,643.70).
