# Third-Party Notices and Licences

DataMind incorporates and interfaces with open-source software and public benchmark datasets. This document lists the respective licences and terms of use.

---

## 1. Google Gemma Models

DataMind is built to support the **Gemma** family of open models (including Gemma 2B, 7B, 9B, 26B, and 31B variants) created by Google DeepMind.

- **Terms of Use:** Gemma is provided under the [Gemma Terms of Use](https://ai.google.dev/gemma/terms).
- **Prohibited Use:** DataMind complies with the Gemma Prohibited Use Policy.
- **Redistribution Notice:** DataMind **does not** redistribute model weights, checkpoints, or proprietary binary artifacts. Users download and run models locally via Ollama or through authorized API endpoints.

---

## 2. Benchmark Datasets

### UCI Online Retail Dataset
- **Citation:** Chen, D. (2012). Online Retail [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5BW33
- **Licence:** Creative Commons Attribution 4.0 International ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/legalcode)).
- **Usage:** Included as a secondary real-world benchmark dataset for transnational e-commerce analytics.

### Chinook Sample Database
- **Source:** [Chinook Database on GitHub](https://github.com/lerocha/chinook-database)
- **Licence:** MIT Licence.
- **Copyright:** (c) 2008-2023 Luis Rocha.

---

## 3. Core Software Dependencies

| Package | Licence | Purpose |
|---|---|---|
| **DuckDB** | MIT Licence | In-process analytical database and user upload session engine |
| **snowflake-connector-python** | Apache License 2.0 | Snowflake cloud data warehouse connectivity |
| **sqlglot** | MIT Licence | AST-based SQL parsing, transpilation, and security guardrails |
| **pydantic** | MIT Licence | Data validation, settings management, and semantic model typing |
| **PyYAML** | MIT Licence | Configuration and semantic model serialization |
| **pytest** | MIT Licence | Automated testing harness |
| **httpx** | BSD 3-Clause | Asynchronous HTTP client for local LLM communication |
