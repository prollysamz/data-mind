# DataMind Datasets Reference & Provenance

This document records the official provenance, source URLs, licenses, row counts, and verification notes for all primary and secondary datasets supported in DataMind.

---

## 1. Primary Evaluation & Demo Dataset (SaaS Enterprise Operations)
- **Source:** Deterministically synthesized enterprise operational dataset modeled on realistic B2B SaaS telemetry, recurring subscriptions, and Zendesk/Jira support tickets.
- **Generator:** `examples/primary/build_demo_data.py` (Fixed PRNG seed = 42 for 100% reproducible byte & row generation).
- **Format:** DuckDB (`examples/primary/demo.duckdb`) & Snowflake (`DATAMIND.PUBLIC.SALES`, `PRODUCTS`, `SUPPORT_TICKETS`).
- **Tables:**
  - `SALES`: 1,450 rows (order_id, line_no, order_date, order_month, product_id, product_name, quantity, amount).
  - `PRODUCTS`: 5 rows (product_id, name, category, monthly_price_usd, release_date).
  - `SUPPORT_TICKETS`: 100 verbatim customer support tickets indexed in SQLite FTS5 (`.datamind/fts.sqlite`).
- **License:** Open Source (Antigravity DataMind Project).

---

## 2. Secondary Real-World Dataset: UCI Online Retail
- **Official Source:** UC Irvine Machine Learning Repository
- **Dataset Title:** Online Retail
- **Official URL:** [https://archive.ics.uci.edu/dataset/352/online+retail](https://archive.ics.uci.edu/dataset/352/online+retail)
- **Donor:** Dr. Daqing Chen, Director of Public Analytics Group, School of Engineering, London South Bank University, London SE1 0AA, UK (`chend@lsbu.ac.uk`).
- **License:** [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/)
- **Total Records:** 541,909 transactions
- **Timeframe:** 01/12/2010 to 09/12/2011
- **File:** `examples/secondary/online_retail/Online_Retail.csv` (~43.9 MB)
- **Columns:**
  - `InvoiceNo`: 6-digit integral number uniquely assigned to each transaction (if begins with 'c', indicates a cancellation).
  - `StockCode`: 5-digit integral number uniquely assigned to each distinct product.
  - `Description`: Product (item) name.
  - `Quantity`: Quantities of each product (item) per transaction.
  - `InvoiceDate`: Invoice date and time (day and time when transaction was generated).
  - `UnitPrice`: Unit price in sterling (£).
  - `CustomerID`: 5-digit integral number uniquely assigned to each customer.
  - `Country`: Name of the country where each customer resides.
- **Verification Invariant:** Loaded directly through the user-uploaded dataset pipeline with zero source file edits.

---

## 3. Secondary Multi-Table Relational Dataset: Chinook Music Store
- **Official Source:** Chinook Sample Database Project
- **Official URL:** [https://github.com/lerocha/chinook-database](https://github.com/lerocha/chinook-database)
- **License:** MIT License
- **File:** `examples/secondary/chinook/chinook_tracks.csv`
- **Columns:**
  - `track_id`: Integer primary key.
  - `name`: Track title.
  - `album_id`: Relational foreign key.
  - `genre`: Music category (Rock, Jazz, Metal, etc.).
  - `composer`: Author / composer name.
  - `milliseconds`: Duration in ms.
  - `bytes`: File size in bytes.
  - `unit_price`: Price per track in USD.
- **Shape:** Relational catalog data testing aggregation and filtering by genre and composer.

---

## 4. Secondary Messy Dataset: Customer Support Feedback
- **Source:** Hand-curated test dataset containing realistic real-world data collection anomalies.
- **File:** `examples/secondary/messy/customer_feedback_messy.csv`
- **Anomalies Tested:**
  - UTF-8 with Byte Order Mark (BOM).
  - Semicolon (`;`) delimiter instead of comma.
  - Duplicate column headers (`notes` repeated).
  - Quoted multiline free-text customer complaints with embedded punctuation and error codes (`HTTP 504`, `$450`).
  - Missing values (sparse `contact_email` and `notes`).
  - Personal Identifiable Information (PII) pattern detection (email addresses flagged with warnings).
- **Verification Invariant:** Successfully ingested, profiled, and confirmed through DataMind without any manual preprocessing.
