# DataMind Benchmark Evaluation Results

- **Provenance Git Commit:** `4ff3def-dirty`
- **Model Used:** `gemma4-e2b-16k`
- **Backend:** Snowflake (SNOWFLAKE_SAMPLE_DATA.TPCH_SF1, warehouse DATAMIND_XS, role DATAMIND_READONLY)
- **Evaluation Timestamp:** 2026-10-18T18:57:10.705003
- **Suite Evaluated:** `tpch`
- **Latency (Uncached):** Median: 3187.3ms | p90: 99437.9ms
- **Overall Pass Rate:** 10 / 10 Passed (100.0% Pass Rate)

### Benchmark Results Table

| ID | Suite | Status | Latency | Details |
|---|---|:---:|---|---|
| `TPCH_REGION_COUNT` | tpch | **PASS** | 99438ms | All numbers, citations, and ground-truth result sets verified |
| `TPCH_CUSTOMER_COUNT` | tpch | **PASS** | 2877ms | All numbers, citations, and ground-truth result sets verified |
| `TPCH_AVG_BALANCE` | tpch | **PASS** | 1946ms | All numbers, citations, and ground-truth result sets verified |
| `TPCH_SEGMENT_BREAKDOWN` | tpch | **PASS** | 1927ms | All numbers, citations, and ground-truth result sets verified |
| `TPCH_URGENT_ORDERS` | tpch | **PASS** | 3187ms | All numbers, citations, and ground-truth result sets verified |
| `TPCH_REVENUE_BY_YEAR` | tpch | **PASS** | 4005ms | All numbers, citations, and ground-truth result sets verified |
| `TPCH_NATIONS_IN_AMERICA` | tpch | **PASS** | 2629ms | All numbers, citations, and ground-truth result sets verified |
| `TPCH_TOP_NATIONS_BY_CUSTOMERS` | tpch | **PASS** | 3251ms | All numbers, citations, and ground-truth result sets verified |
| `TPCH_REVENUE_AFTER_DISCOUNT` | tpch | **PASS** | 3436ms | All numbers, citations, and ground-truth result sets verified |
| `TPCH_ORDERS_WITH_LINE_ITEMS` | tpch | **PASS** | 1942ms | All numbers, citations, and ground-truth result sets verified |
