# DataMind Benchmark Evaluation Results

- **Provenance Git Commit:** `4b77aad`
- **Model Used:** `gemma4-e2b-16k`
- **Backend:** Snowflake (DATAMIND.PUBLIC, warehouse DATAMIND_XS, role DATAMIND_READONLY)
- **Evaluation Timestamp:** 2026-10-18T12:19:33.946006
- **Suite Evaluated:** `business`
- **Latency (Uncached):** Median: 994.9ms | p90: 2988.2ms
- **Overall Pass Rate:** 20 / 21 Passed (95.2% Pass Rate)

### Benchmark Results Table

| ID | Suite | Status | Latency | Details |
|---|---|:---:|---|---|
| `Q_MOM_DECLINE` | business | **PASS** | 12877ms | All numbers, citations, and ground-truth result sets verified |
| `Q_MIXED_REVENUE_SUPPORT` | business | **PASS** | 3140ms | All numbers, citations, and ground-truth result sets verified |
| `Q_TOTAL_REVENUE` | business | **PASS** | 944ms | All numbers, citations, and ground-truth result sets verified |
| `Q_PRODUCTS_CATALOG` | business | **PASS** | 1260ms | All numbers, citations, and ground-truth result sets verified |
| `Q_TOP_SELLING_PRODUCT` | business | **PASS** | 1070ms | All numbers, citations, and ground-truth result sets verified |
| `Q_TOTAL_UNITS_SOLD` | business | **PASS** | 779ms | All numbers, citations, and ground-truth result sets verified |
| `Q_AVG_ORDER_VALUE` | business | **PASS** | 830ms | All numbers, citations, and ground-truth result sets verified |
| `Q_MONTHLY_REVENUE_TREND` | business | **FAIL** | 2988ms | Failures: Result-set mismatch (expected 5 rows matching ground truth SQL) |
| `Q_LOGISTICS_CATEGORY_REVENUE` | business | **PASS** | 1125ms | All numbers, citations, and ground-truth result sets verified |
| `Q_SECURITY_CATEGORY_REVENUE` | business | **PASS** | 835ms | All numbers, citations, and ground-truth result sets verified |
| `Q_NOVASHIP_MARCH_SALES` | business | **PASS** | 995ms | All numbers, citations, and ground-truth result sets verified |
| `Q_NOVASHIP_FEB_SALES` | business | **PASS** | 1001ms | All numbers, citations, and ground-truth result sets verified |
| `Q_ORDERS_PER_PRODUCT` | business | **PASS** | 1324ms | All numbers, citations, and ground-truth result sets verified |
| `Q_CRITICAL_SUPPORT_TICKETS` | business | **PASS** | 731ms | All numbers, citations, and ground-truth result sets verified |
| `Q_OUTAGE_TICKETS_PRODUCT` | business | **PASS** | 808ms | All numbers, citations, and ground-truth result sets verified |
| `Q_TICKETS_PER_PRODUCT` | business | **PASS** | 1121ms | All numbers, citations, and ground-truth result sets verified |
| `Q_MAX_SINGLE_ORDER` | business | **PASS** | 594ms | All numbers, citations, and ground-truth result sets verified |
| `Q_MIN_SINGLE_ORDER` | business | **PASS** | 568ms | All numbers, citations, and ground-truth result sets verified |
| `Q_AVG_QUANTITY_PER_LINE` | business | **PASS** | 650ms | All numbers, citations, and ground-truth result sets verified |
| `Q_PRODUCT_COUNT_BY_CAT` | business | **PASS** | 1024ms | All numbers, citations, and ground-truth result sets verified |
| `Q_CLOUDSYNC_TOTAL_REVENUE` | business | **PASS** | 819ms | All numbers, citations, and ground-truth result sets verified |
