# DataMind Benchmark Evaluation Results

- **Provenance Git Commit:** `5fc44b2`
- **Model Used:** `gemma4:e2b` (Local 16k context Ollama)
- **Backend:** DuckDB (`examples/primary/demo.duckdb`) & Snowflake Data Warehouse
- **Evaluation Timestamp:** 2026-10-17T19:20:03.464184
- **Suite Evaluated:** `held_out_sealed`
- **Latency (Uncached):** Median: 2264.0ms | p90: 3459.4ms
- **Overall Pass Rate:** 15 / 20 Passed (75.0% Pass Rate)

### Benchmark Results Table

| ID | Suite | Status | Latency | Details |
|---|---|:---:|---|---|
| `S_Q1_AVG_UNIT_PRICE_BY_CAT` | held_out_sealed | **FAIL** | 5866ms | Failures: Result-set mismatch (expected 5 rows matching ground truth SQL) |
| `S_Q2_ORDERS_OVER_1000` | held_out_sealed | **FAIL** | 2460ms | Failures: citation_discrepancy |
| `S_Q3_PRODUCT_HIGH_SEVERITY_TICKETS` | held_out_sealed | **PASS** | 3001ms | All numbers, citations, and ground-truth result sets verified |
| `S_Q4_FEB_REVENUE_PERCENT` | held_out_sealed | **PASS** | 3025ms | All numbers, citations, and ground-truth result sets verified |
| `S_Q5_DISTINCT_SALE_DATES` | held_out_sealed | **PASS** | 1677ms | All numbers, citations, and ground-truth result sets verified |
| `S_Q6_BASE_PRICE_SPREAD` | held_out_sealed | **PASS** | 2054ms | All numbers, citations, and ground-truth result sets verified |
| `S_Q7_LOGISTICS_SUPPORT_TICKETS` | held_out_sealed | **FAIL** | 2039ms | Failures: Result-set mismatch (expected 1 rows matching ground truth SQL) |
| `S_Q8_SINGLE_UNIT_ORDERS` | held_out_sealed | **FAIL** | 2197ms | Failures: citation_discrepancy |
| `S_Q9_TICKETS_BY_PRIORITY` | held_out_sealed | **PASS** | 2730ms | All numbers, citations, and ground-truth result sets verified |
| `S_Q10_TOTAL_CATALOG_PRODUCTS` | held_out_sealed | **PASS** | 1714ms | All numbers, citations, and ground-truth result sets verified |
| `S_Q11_JANUARY_2026_REVENUE` | held_out_sealed | **PASS** | 2264ms | All numbers, citations, and ground-truth result sets verified |
| `S_Q12_LOWEST_REALIZED_PRICE_PRODUCT` | held_out_sealed | **FAIL** | 3459ms | Failures: product_mismatch (expected CloudSync), Result-set mismatch (expected 1 rows matching ground truth SQL) |
| `S_Q13_TOTAL_UNITS_SOLD_OVERALL` | held_out_sealed | **PASS** | 1870ms | All numbers, citations, and ground-truth result sets verified |
| `S_Q14_TOTAL_SECURITY_REVENUE` | held_out_sealed | **PASS** | 2519ms | All numbers, citations, and ground-truth result sets verified |
| `S_Q15_AVERAGE_ORDER_QUANTITY` | held_out_sealed | **PASS** | 1896ms | All numbers, citations, and ground-truth result sets verified |
| `S_Q16_MAX_LINE_ITEM_AMOUNT` | held_out_sealed | **PASS** | 1449ms | All numbers, citations, and ground-truth result sets verified |
| `S_Q17_MARCH_2026_ORDER_COUNT` | held_out_sealed | **PASS** | 2495ms | All numbers, citations, and ground-truth result sets verified |
| `S_Q18_CRITICAL_PRIORITY_PRODUCT` | held_out_sealed | **PASS** | 2763ms | All numbers, citations, and ground-truth result sets verified |
| `S_Q19_AVERAGE_CATALOG_BASE_PRICE` | held_out_sealed | **PASS** | 1531ms | All numbers, citations, and ground-truth result sets verified |
| `S_Q20_TOTAL_OUTAGE_TICKETS` | held_out_sealed | **PASS** | 1563ms | All numbers, citations, and ground-truth result sets verified |
