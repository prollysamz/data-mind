# DataMind: 3-Minute Live Demo Script

This script walks through the core capabilities of DataMind in under 3 minutes, covering deterministic verification, interactive citations, live CSV uploads, adversarial defenses, and cost control.

---

## Preparation (Before Recording)

1. Ensure Ollama is running with Gemma:
   ```bash
   ollama run gemma4:e2b
   ```
2. Start the DataMind server with uploads enabled:
   ```bash
   datamind serve --enable-uploads --port 8080
   ```
3. Open `http://localhost:8080` in your browser.

---

## 3-Minute Walkthrough Flow

### [00:00 - 00:30] Scene 1: Main Data & Month-over-Month Revenue Decline
1. **Action:** Click the sample chip or type:
   > *"Which products experienced the largest month-over-month revenue decline and what were customer complaints about that product?"*
2. **Observe:**
   - Pure SVG diverging bar chart renders dynamically.
   - Narrative answer identifies **Novaship** with **-$53,803.23** decline and previous month sales of **$82,160.45**.
   - Verification badge displays **VERIFIED (100% Grounded)** with 5 numbers verified to the exact cent.
   - SQL drawer displays real executed SQL and query ID.

### [00:30 - 00:50] Scene 2: Interactive Provenance & Verbatim Audit
1. **Action:** Click the number `$53,803.23` in the answer or chart.
   - **Observe:** The corresponding table row `Novaship | 2026-03-01` flashes with a golden highlight ring.
2. **Action:** Click the document citation pill `[[D:SUPPORT_TICKETS:TK-1002]]` next to the outage description.
   - **Observe:** The document drawer slides out displaying the verbatim customer support ticket with the highlighted sentence: *"Customer experienced 504 gateway timeout on billing portal for Novaship. Repeated attempts caused duplicate transactions of $120.00."*

### [00:50 - 01:10] Scene 3: Follow-Up & Filter
1. **Action:** Type follow-up query:
   > *"What was Novaship's sales revenue in February 2026?"*
2. **Observe:**
   - Model filters for February (`$82,160.45 [[Q1:R1]]`).
   - Single-value KPI card displays `$82,160.45`.
   - Verified clean with 0 discrepancies.

### [01:10 - 01:30] Scene 4: Honest Refusal on Missing Data
1. **Action:** Type an unanswerable question:
   > *"What were the employee salaries of the support engineering team that handled ticket TK-1002?"*
2. **Observe:**
   - Agent refuses honestly without executing ungrounded SQL.
   - States clearly: *"The schema contains sales and support tickets, but does not contain employee salary or internal compensation data."*
   - SQL Guard blocks attempts to query unauthorized tables.

### [01:30 - 02:10] Scene 5: Live CSV Upload & Instant Verification
1. **Action:** Click **"Upload CSV Dataset"** in the top navigation.
2. **Action:** Drag and drop `tests/fixtures/customer_feedback_messy.csv`.
3. **Observe:**
   - Immediate client-side validation (BOM decoded, Latin-1 notice, PII heuristic flags contact email).
   - Data profiling table displays column types, null %, min/max, distinct counts.
   - Review draft semantic model, set currency to USD `$`, and click **"Confirm & Query Dataset"**.
4. **Action:** Type:
   > *"What are the most frequent customer complaints in this dataset?"*
5. **Observe:** Verified answer with citations to the newly created isolated DuckDB session.
6. **Action:** Click **"Delete My Data"** to purge the session.

### [02:10 - 02:35] Scene 6: Adversarial Defense & Mutation Catch Rate
1. **Action:** Show the verifier catching a planted wrong number:
   - Type or demonstrate question with planted discrepancy ($999,999.00 vs cited row).
   - **Observe:** Badge turns amber **"Verification Discrepancy"** and lists exact cell diff: *"Claimed $999,999.00 does not match cell amount $28,357.22"*.
2. **Action:** Switch to terminal and show the mutation report:
   ```bash
   datamind eval --suite verifier
   ```
   - Highlight the **100.0% catch rate** across 53 automated mutations (perturbations, magnitude, direction flips, currency swaps, citation tampering).

### [02:35 - 03:00] Scene 7: Model Swap & Cost Metering
1. **Action:** Show the budget and cost meter:
   ```bash
   datamind usage
   ```
   - Show 243 calls, 675,601 tokens tracked, **$0.00 spent**, **$10.00 budget remaining**.
2. **Action:** Demonstrate model swappability:
   - Point out that local Gemma E2B (2B parameters) achieves 75.0% on the sealed set with zero cloud spend, and can be swapped for Gemma 26B/31B with the exact same guard and verifier code.
