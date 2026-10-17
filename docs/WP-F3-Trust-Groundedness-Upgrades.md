# WP-F3 Report: Trust & Groundedness Upgrades

**Work Package:** WP-F3  
**Status:** Completed & Certified  
**Key Commit:** `a3013aa`  
**Test Suite:** [`eval/mutation.py`](file:///d:/HackOctober/eval/mutation.py), [`tests/test_ast_linter.py`](file:///d:/HackOctober/tests/test_ast_linter.py)

---

## 1. Problem Statement: The "Verified but Wrong" Silent Error

In early systems, a deterministic verifier only checked that numbers in text matched numbers returned in SQL rows. 
However, this left an insidious blind spot: **The "Verified but Wrong" Silent Error**.
* *Example:* If an LLM generated a SQL query with a missing `WHERE order_status = 'delivered'` filter or a join Cartesian fan-out, the query would execute, produce inflated numbers, the LLM would cite those numbers accurately, and the naive verifier would mark it "PASS"—even though the business answer was completely wrong!

WP-F3 closed this gap through deterministic query AST linting, assumptions disclosure, and comprehensive adversarial verification.

---

## 2. Key Trust Implementations

### 2.1 Deterministic Query AST Linter
* Uses `sqlglot` to parse generated SQL into an Abstract Syntax Tree before execution.
* Checks for:
  1. **Missing GROUP BY columns** or non-deterministic aggregations.
  2. **Cartesian Fan-Out:** Alerts if two 1-to-many relationship tables are joined without proper grouping or distinct primary keys.
  3. **Schema Boundary Violations:** Blocks queries attempting to reference non-existent columns.
  4. **Suspicious Date Arithmetic:** Ensures timestamps use timezone-safe truncation.

### 2.2 Transparent Assumptions Card
* Automatically introspects every generated SQL query and renders an **Assumptions Card** in the UI:
  * Inferred temporal grain (e.g. `Monthly (order_purchase_timestamp)`).
  * Inferred filters (e.g. `Excluding canceled/unavailable orders`).
  * Inferred metric expressions (e.g. `SUM(price) as gmv`).
* Allows human business users to immediately inspect and challenge assumptions.

### 2.3 12-Category Adversarial Mutation Benchmark
Built an adversarial suite ([`eval/mutation.py`](file:///d:/HackOctober/eval/mutation.py)) testing 73 distinct real-world corruptions across 12 categories:
1. Number Perturbation (+/- 1.00 or random drift)
2. Currency Unit Swaps ($ to €, BRL to USD)
3. Magnitude Skews (10x, 100x scaling)
4. Fabricated Citations (`[[Q99:R99]]`)
5. Deleted Citations (uncited bare metrics)
6. Directional Inversions (growth vs decline)
7. Entity Swaps (switching product names)
8. Temporal Drift (wrong month/year in narrative)
9. Percent vs Absolute Number Confusions
10. Aggregation Hallucinations (claiming average when sum was calculated)
11. Extrapolation Beyond Evidence
12. Schema Boundary Violations

---

## 3. Empirical Benchmark Results

```
======================================================================
DATAMIND WP-F3 ADVERSARIAL MUTATION VERIFICATION BENCHMARK
======================================================================
Total Adversarial Mutations Tested:  73
Mutations Detected & Caught:         73
Mutations Slipped Through:            0
----------------------------------------------------------------------
Deterministic Verifier Catch Rate:   100.0% (73/73)
======================================================================
```

Every single adversarial corruption was deterministically intercepted with a specific diagnostic message.
