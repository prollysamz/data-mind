# DataMind Work Packages (WP) Master Index

This document provides a comprehensive index of all engineering Work Packages (WPs) executed during DataMind's development, their objectives, key git commits, empirical benchmarks, and links to detailed reports.

---

## Work Packages Summary Matrix

| Package | Title | Primary Focus | Key Commits | Empirical Milestone | Full Report |
| :--- | :--- | :--- | :---: | :---: | :---: |
| **WP-F0** | **Integrity Reset & Authenticity Charter** | Purging synthetic claims, establishing evaluation run ledgers & secret hygiene | `3560b80`<br>`1c47a34` | Immutable run ledger established; zero unverified claims | [Read WP-F0 Report](WP-F0-Integrity-Charter.md) |
| **WP-F1** | **Authentic Data Ingestion** | Ingesting 100k-order Olist E-Commerce dataset across DuckDB & Snowflake | `c8cbd68` | 9 tables, 100,000 orders, full dialect parity | [Read WP-F1 Report](WP-F1-Authentic-Data-Ingestion.md) |
| **WP-F2** | **Small Model Tuning** | Scaffolding techniques for Gemma 4 (compilation lanes, schema pruning, few-shot leakage guard) | `28edeb1` | 100% `olist_dev` claim **withdrawn** (came from a hard-coded lane, since removed) | [Read WP-F2 Report](WP-F2-Small-Model-Tuning.md) |
| **WP-F3** | **Trust & Groundedness Upgrades** | Eliminating "verified but wrong" errors via SQL AST linting & assumptions cards | `a3013aa` | **100% Catch Rate (73/73)** across 12 mutation categories | [Read WP-F3 Report](WP-F3-Trust-Groundedness-Upgrades.md) |
| **WP-F4** | **Review Classification & Sentiment** | Local Gemma review categorization, sentiment star agreement, and verbatim quote verification | `6823fa0` | **53.0% sentiment agreement (106/200)**, 80.0% topic agreement (40/50) | [Read WP-F4 Report](WP-F4-Review-Classification-Sentiment.md) |
| **WP-F5** | **Sealed Evaluation & Human Audit** | SHA-256 sealed question commitment, 40-item human citation review | `ca6b005` | Claims **withdrawn**: agent-authored questions, digest mismatch, citation sheet not a real human audit | [Read WP-F5 Report](WP-F5-Sealed-Evaluation-Human-Audit.md) |
| **WP-F6** | **Demonstration Script & MCP Integration** | 3-minute timed live walkthrough script & Model Context Protocol stdio server | `9c43564`<br>`3c5d244` | Video recording skipped per user instruction; live script & MCP server delivered | [Read WP-F6 Report](WP-F6-Demo-Script-And-Presentation.md) |
| **WP-F7** | **Packaging, Diagnostics & Freeze** | `eval-freeze-v2` tag, `datamind doctor` CLI diagnostics, automated GitHub Actions CI | `1a34ab2` | Tests pass in CI (now 234); no freeze tag exists; CI has no lint/type checks | [Read WP-F7 Report](WP-F7-Packaging-And-Artifact-Freeze.md) |
| **WP-F8** | **Model Registry & Trust Layer** | Air-gap presets, Bedrock Mantle integration, SHA-256 receipts, second opinion, live red-team | `d556f5e`<br>`8db5b44`<br>`a756a3f` | Live Bedrock connected; 100% red-team catch rate; centered modals | [Read WP-F8 Report](WP-F8-Trust-Model-Registry-Red-Team.md) |

---

## Evaluation Benchmark Summary (corrected 2026-10-18)

| Suite | Count | Result | Notes |
|---|:---:|:---:|---|
| Olist dev set (`olist_dev.yaml`) | 30 | Not yet re-run | Earlier 100% came from the removed hard-coded lane |
| Business suite (synthetic DuckDB) | 21 | 19-20 / 21 | Three runs, `gemma4:e2b` at 16k context; development tuning set |
| Trust & guardrails suite | 6 | 6 / 6 | Three runs |
| Verifier mutation suite | 73 | 73 / 73 | Checks numbers and citations, not SQL intent |
| Review sentiment agreement (Olist) | 200 | 53.0% | vs. customer star ratings |
| Automated tests (pytest) | 234 | 234 / 234 | Offline, no credentials |

There is no independent, human-authored sealed evaluation and no human citation audit yet. See [eval/HISTORY.md](../eval/HISTORY.md) for the full record.
