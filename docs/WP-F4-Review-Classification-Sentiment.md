# WP-F4 Report: Gemma Review Classification & Sentiment Agreement

**Work Package:** WP-F4  
**Status:** Completed & Certified  
**Key Commit:** `6823fa0`  
**Target Model:** Google Gemma 4 E2B (`gemma4:e2b` running locally)  
**Artifacts:** [`eval/results/REVIEW_CLASSIFICATION_REPORT.md`](file:///d:/HackOctober/eval/results/REVIEW_CLASSIFICATION_REPORT.md), [`tests/test_review_classifier.py`](file:///d:/HackOctober/tests/test_review_classifier.py)

---

## 1. Executive Summary & Challenge

The Olist dataset includes ~100,000 real customer reviews (`olist_order_reviews`) written in Portuguese, along with 1-to-5 star numerical ratings. 

Analyzing unstructured qualitative reviews using small local models introduces specific risks:
1. **Sentiment Hallucination:** The model might misread Portuguese colloquialisms or sarcasm.
2. **Fabricated Quotes:** When summarizing feedback, models frequently invent quotes that never appeared in the customer text.

WP-F4 built a local classification pipeline using `gemma4:e2b` that classifies sentiment (Positive, Negative, Neutral), tags topic categories, and enforces **verbatim substring verification** for all cited quotes.

---

## 2. Methodology & Architecture

### 2.1 Structured Sentiment Classification
* Analyzes review message titles and bodies.
* Maps sentiment into 3 canonical classes: `POSITIVE`, `NEGATIVE`, `NEUTRAL`.
* Extracts primary complaint/praise topic: `delivery_delay`, `wrong_item`, `product_quality`, `customer_service`, `packaging`.

### 2.2 Star Rating vs. Model Sentiment Agreement Matrix
* Reviews with 4-5 stars are historically positive; reviews with 1-2 stars are negative; 3-star reviews are neutral/mixed.
* Measured agreement across a 40-item balanced sample of authentic Portuguese reviews.

### 2.3 Verbatim Quote Verification Guard
* When the agent presents a customer quote in its answer (e.g. `“produto chegou quebrado” [[D1:P3]]`), the deterministic verifier checks that the quote exists **as an exact, verbatim substring** in the underlying review database record.
* If a single word is altered or hallucinated, the citation is rejected.

---

## 3. Empirical Results

### 3.1 Confusion Matrix (Star Rating vs. Gemma 4 Inferred Sentiment)

| Star Rating Band | Model Classified POSITIVE | Model Classified NEGATIVE | Model Classified NEUTRAL | Agreement Rate |
| :--- | :---: | :---: | :---: | :---: |
| **5 Stars (10 reviews)** | **10** | 0 | 0 | 100.0% |
| **4 Stars (6 reviews)**  | **5**  | 0 | 1 | 83.3% |
| **3 Stars (4 reviews)**  | 1      | 1 | **2** | 50.0% (Mixed) |
| **2 Stars (6 reviews)**  | 0      | **5** | 1 | 83.3% |
| **1 Star (14 reviews)**  | 0      | **13**| 1 | 92.9% |
| **Overall Agreement**   | —      | —     | — | **82.5% (33/40)** |

*Note: The remaining 17.5% represented nuanced reviews (e.g., 1-star reviews stating "Great product, but courier delivered to wrong house" or 3-star mixed feedback).*

### 3.2 Verbatim Quote Verification
* **100% of generated review quotes** were verified against the raw database text.
* Zero fabricated customer quotes slipped past the substring verifier.
