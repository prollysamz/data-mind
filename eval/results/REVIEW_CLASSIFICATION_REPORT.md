# WP-F4 Evaluation Report: Review Sentiment & Topic Classification

**Evaluation Date:** 2026-10-17 18:27:01 UTC  
**Model:** Gemma 4 E2B (`gemma4:e2b`)  
**Prompt Version:** `v1.0`  
**Dataset:** Brazilian E-Commerce Public Dataset by Olist (`data/olist/olist.duckdb`)  
**Sample Size:** 200 customer reviews with text  
**Table Stored:** `olist_review_classifications` (with `model_derived = true`)  

---

## 1. Sentiment Agreement vs Customer Star Rating

*Ground Truth Mapping:* Star Ratings 1-2 $\to$ Negative, 3 $\to$ Neutral, 4-5 $\to$ Positive.  
*Overall Agreement (Accuracy):* **53.0%** (106 / 200)

### Confusion Matrix

| Actual \ Predicted | Negative | Neutral | Positive | Total |
| :--- | :---: | :---: | :---: | :---: |
| **Negative (1-2 Stars)** | 16 | 29 | 6 | 51 |
| **Neutral (3 Stars)** | 3 | 5 | 4 | 12 |
| **Positive (4-5 Stars)** | 1 | 51 | 85 | 137 |
| **Total Predicted** | 20 | 85 | 95 | 200 |

### Classification Metrics

| Class | Precision | Recall | F1-Score | Support |
| :--- | :---: | :---: | :---: | :---: |
| **Negative** | 0.8 | 0.314 | 0.451 | 51 |
| **Neutral** | 0.059 | 0.417 | 0.103 | 12 |
| **Positive** | 0.895 | 0.62 | 0.733 | 137 |

---

## 2. Topic Classification Accuracy

- **Sample Size:** 50 verified reviews
- **Topic Categories:** Delivery Delay, Product Quality, Wrong/Missing Item, Seller Communication, Price/Value, Other
- **Topic Agreement:** **80.0%** (40 / 50)

---

## 3. Verbatim Quoting Verification

- **Verbatim Clean Test:** PASSED (All quoted spans verified in cited source chunks)
- **Fabricated Quote Injection Test:** PASSED (Tampered/invented quotes successfully caught and flagged)
- **Model Derived Invariant:** 100% of persisted rows (200 rows) in `olist_review_classifications` are explicitly flagged with `model_derived = true`.

---

## 4. Cloud Egress & Air-Gap Audit

- **Cloud API Calls:** 0 (100% local Gemma execution via Ollama)
- **Outbound Data Rows:** 0
- **Total Incurred Cost:** $0.00 USD
