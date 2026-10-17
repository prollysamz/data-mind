# WP-F8 Report: Model Registry, Trust Architecture & Red-Team

**Work Package:** WP-F8  
**Status:** Completed & Certified  
**Key Commits:** `d556f5e`, `8db5b44`, `a756a3f`  
**Artifacts:** [`src/datamind/llm/models.py`](file:///d:/HackOctober/src/datamind/llm/models.py), [`src/datamind/guardrails/egress_guard.py`](file:///d:/HackOctober/src/datamind/guardrails/egress_guard.py), [`src/datamind/trust/receipts.py`](file:///d:/HackOctober/src/datamind/trust/receipts.py), [`src/datamind/agent/second_opinion.py`](file:///d:/HackOctober/src/datamind/agent/second_opinion.py)

---

## 1. Executive Summary & Purpose

WP-F8 delivered the core **Enterprise Trust Layer** for DataMind, solving key operational and governance challenges:
1. Flexible model selection across **Local Air-Gapped** and **Cloud Metered (AWS Bedrock)** models.
2. Hard fail-closed egress boundaries preventing database leaks to the cloud.
3. Cryptographic proof of query execution through tamper-evident receipts.
4. Independent verification through cross-model second opinions.
5. In-browser live adversarial red-team verification.

---

## 2. Key Architecture Components

### 2.1 Unified Model Registry & Presets
* Manages local models (`gemma4:e2b`, `gemma4:e4b` via Ollama) and cloud models (`google.gemma-4-26b-a4b`, `google.gemma-4-31b`, `anthropic.claude-3-haiku` via AWS Bedrock Mantle).
* Offers pre-configured governance presets:
  * **Local Only (Air-Gapped):** 100% on-device execution with zero cloud egress.
  * **Hybrid Privacy (Schema-Only Cloud):** Sends only question and schema summary to cloud; 0 database rows or document passages ever leave the host.
  * **Cloud High Accuracy (Bedrock Metered):** Full reasoning executed on Bedrock with strict per-query token and dollar budget limits ($10 cap).
  * **Second Opinion (Cross-Model Agreement):** Dual-model consensus pipeline.

### 2.2 Egress Sentinel Guard & Canary Traps
* Scans all outbound prompts before cloud dispatch.
* Automatically blocks raw database row values, API keys, credentials, and planted canary trap secrets (`SENTINEL_ROW_SECRET`).

### 2.3 Cryptographic SHA-256 Receipts
* Builds a Merkle-like tamper-evident hash chain linking:
  * Question text $\rightarrow$ Generated SQL $\rightarrow$ Evidence rows $\rightarrow$ Verification report $\rightarrow$ Data egress manifest.
* Produces an immutable `receipt.json` and a standalone WebCrypto HTML verification file.
* Verifiable via CLI: `datamind verify-receipt <receipt.json> [--replay]`.

### 2.4 Cross-Model Second Opinion
* Executes two distinct models (e.g., Bedrock Gemma 4 26B vs Local Gemma 4 E2B) independently on the same business question.
* Compares generated SQL trees, executed row sets, and renders an **Assumptions & Method Diff** highlighting any logical divergence.

### 2.5 Live Adversarial Red-Team Challenge
* Interactive verification UI allowing auditors to execute 6 real-time adversarial corruptions:
  1. Planted Canary Trap Leak
  2. Value Perturbation (+100.00)
  3. Currency Swap ($ to €)
  4. Fabricated Citation ID (`[[Q99:R99]]`)
  5. Deleted Citation (Bare Metric)
  6. Direction Flip (Growth vs Decline)
* **Results:** 100% Catch Rate caught deterministically by the verifier with explicit catch diagnostics.

---

## 3. UI/UX Centering & Modal Integration
* All trust tools (Cloud Consent, Receipt Inspector, Second Opinion, Red-Team Challenge) feature centered modal popups with backdrop blur (`backdrop-filter: blur(12px)`) and responsive layouts.
