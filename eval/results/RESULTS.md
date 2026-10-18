# DataMind Benchmark Evaluation Results

- **Provenance Git Commit:** `50e54a6-dirty`
- **Model Used:** `gemma4-e2b-16k`
- **Backend:** Snowflake (SNOWFLAKE_SAMPLE_DATA.TPCH_SF1, warehouse DATAMIND_XS, role DATAMIND_READONLY)
- **Evaluation Timestamp:** 2026-10-18T18:22:52.527011
- **Suite Evaluated:** `tpch`
- **Latency (Uncached):** Median: 1663.4ms | p90: 3208.9ms
- **Overall Pass Rate:** 10 / 10 Passed (100.0% Pass Rate)

### Benchmark Results Table

| ID | Suite | Status | Latency | Details |
|---|---|:---:|---|---|
| `TPCH_REGION_COUNT` | tpch | **PASS** | 3209ms | All numbers, citations, and ground-truth result sets verified |
| `TPCH_CUSTOMER_COUNT` | tpch | **PASS** | 824ms | All numbers, citations, and ground-truth result sets verified |
| `TPCH_AVG_BALANCE` | tpch | **PASS** | 957ms | All numbers, citations, and ground-truth result sets verified |
| `TPCH_SEGMENT_BREAKDOWN` | tpch | **PASS** | 1663ms | All numbers, citations, and ground-truth result sets verified |
| `TPCH_URGENT_ORDERS` | tpch | **PASS** | 1089ms | All numbers, citations, and ground-truth result sets verified |
| `TPCH_REVENUE_BY_YEAR` | tpch | **PASS** | 3178ms | All numbers, citations, and ground-truth result sets verified |
| `TPCH_NATIONS_IN_AMERICA` | tpch | **PASS** | 1985ms | All numbers, citations, and ground-truth result sets verified |
| `TPCH_TOP_NATIONS_BY_CUSTOMERS` | tpch | **PASS** | 2198ms | All numbers, citations, and ground-truth result sets verified |
| `TPCH_REVENUE_AFTER_DISCOUNT` | tpch | **PASS** | 1205ms | All numbers, citations, and ground-truth result sets verified |
| `TPCH_ORDERS_WITH_LINE_ITEMS` | tpch | **PASS** | 924ms | All numbers, citations, and ground-truth result sets verified |
