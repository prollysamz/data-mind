# WP-F6 Report: Demonstration Script, Presentation & MCP Integration

**Work Package:** WP-F6  
**Status:** Completed (Video Skipped per User Direction; Script & Protocol Preserved)  
**Key Commits:** `9c43564`, `3c5d244`  
**Artifacts:** [`docs/demo-script.md`](file:///d:/HackOctober/docs/demo-script.md), [`src/datamind/mcp_server.py`](file:///d:/HackOctober/src/datamind/mcp_server.py)

---

## 1. Executive Summary & Purpose

WP-F6 was originally scheduled for the **3-Minute Demonstration Video, Screencast Recording, and Live Presentation Architecture**. 

During sprint execution, the video recording was skipped per explicit user instruction (*"continue do it fast , video part skip it"*), prioritizing engineering completion of the live Bedrock integration, trust layers, and empirical benchmark evaluations.

However, all technical and structural presentation deliverables for WP-F6 were fully implemented:
1. A timed **3-Minute Live Walkthrough Script** ([`docs/demo-script.md`](file:///d:/HackOctober/docs/demo-script.md)).
2. An industry-standard **Model Context Protocol (MCP)** stdio server ([`src/datamind/mcp_server.py`](file:///d:/HackOctober/src/datamind/mcp_server.py)).
3. CLI presentation subcommands (`datamind demo`, `datamind mcp`).

---

## 2. 3-Minute Demonstration Flow

For live presentations, judges, or evaluation recordings, the demonstration is organized into five timed scenes:

| Scene | Duration | Feature Demonstrated | User Action | Expected System Response |
| :--- | :---: | :--- | :--- | :--- |
| **Scene 1** | 00:00 - 00:30 | **Month-over-Month Decline** | Ask: *"Which products experienced revenue decline?"* | Renders diverging SVG bar chart, cites Novaship (-$53,803.23), displays 100% verified badge. |
| **Scene 2** | 00:30 - 00:50 | **Interactive Provenance Audit** | Click `$53,803.23` and `[[D:SUPPORT_TICKETS:TK-1002]]` | Table row highlights in gold; document drawer slides out with verbatim customer complaint. |
| **Scene 3** | 00:50 - 01:10 | **Follow-up & Temporal Filtering**| Ask: *"What was Novaship sales in Feb 2026?"* | Fast single-value KPI card rendered with zero latency. |
| **Scene 4** | 01:10 - 01:30 | **Schema Boundary Refusal** | Ask: *"What are the employee salaries of support team?"* | Honest refusal: explains salary is absent from catalog, preventing hallucination. |
| **Scene 5** | 01:30 - 02:15 | **Adversarial Red-Team Challenge** | Click **"🛡️ Red-Team Attack"** | Executes 6 live corruptions; verifier catches all (100% catch rate). |
| **Scene 6** | 02:15 - 03:00 | **Verifiable Receipts & Models** | Click **"📜 Verifiable Receipt"** and toggle Bedrock preset | Merkle-like SHA-256 hash shown; downloads `receipt.json`. |

---

## 3. Model Context Protocol (MCP) Integration

WP-F6 also delivered the standard Model Context Protocol interface, allowing DataMind to serve as a verifiable data provider for external host agents:

```bash
# Launch DataMind as an MCP Stdio Server
datamind mcp
```

### Exposed MCP Tools:
* `datamind_ask`: Executes natural language questions with verified provenance citations.
* `datamind_list_tables`: Discovers verified tables and semantic metric definitions.
* `datamind_describe_table`: Returns column schemas, types, and primary key relationships.
