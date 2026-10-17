# DataMind Benchmark Evaluation Results

**Model Used:** `gemma4:e2b` | **Dataset:** `examples/primary/demo.duckdb`
**Last Run:** 2026-10-17T13:20:02.160767 | **Suite:** `held_out_sealed`
**Summary:** 6 / 10 Passed (60.0% Pass Rate)

| ID | Suite | Status | Duration | Details |
|---|---|:---:|---|---|
| `S_Q1_AVG_UNIT_PRICE_BY_CAT` | held_out_sealed | **FAIL** | 21093ms | Failures: Result-set mismatch (expected 5 rows matching ground truth SQL) |
| `S_Q2_ORDERS_OVER_1000` | held_out_sealed | **FAIL** | 2728ms | Failures: citation_discrepancy |
| `S_Q3_PRODUCT_HIGH_SEVERITY_TICKETS` | held_out_sealed | **PASS** | 3172ms | All numbers, citations, and ground-truth result sets verified |
| `S_Q4_FEB_REVENUE_PERCENT` | held_out_sealed | **FAIL** | 14920ms | Failures: no_evidence, Agent executed no SQL queries |
| `S_Q5_DISTINCT_SALE_DATES` | held_out_sealed | **PASS** | 2212ms | All numbers, citations, and ground-truth result sets verified |
| `S_Q6_BASE_PRICE_SPREAD` | held_out_sealed | **PASS** | 2140ms | All numbers, citations, and ground-truth result sets verified |
| `S_Q7_LOGISTICS_SUPPORT_TICKETS` | held_out_sealed | **PASS** | 3824ms | All numbers, citations, and ground-truth result sets verified |
| `S_Q8_SINGLE_UNIT_ORDERS` | held_out_sealed | **FAIL** | 2170ms | Failures: citation_discrepancy |
| `S_Q9_TICKETS_BY_PRIORITY` | held_out_sealed | **PASS** | 2660ms | All numbers, citations, and ground-truth result sets verified |
| `S_Q10_TOTAL_CATALOG_PRODUCTS` | held_out_sealed | **PASS** | 1832ms | All numbers, citations, and ground-truth result sets verified |
