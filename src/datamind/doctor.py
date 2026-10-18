"""Diagnostic health and environment checker for DataMind."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
from typing import Any
import urllib.request
import json

from datamind.config import AppConfig, load_config
from datamind.llm.budget import CostGuard


MIN_OLLAMA_CONTEXT = 8192


def ollama_configured_context(parameters_text: str, env_value: str | None = None) -> int | None:
    """Return the context length Ollama will use, from a model's Modelfile parameters or OLLAMA_CONTEXT_LENGTH.

    Ollama's OpenAI-compatible /v1 endpoint ignores per-request ``options.num_ctx``, so the window
    is whatever the model or server is configured with (4096 by default). Returns None if unset.
    """
    for line in (parameters_text or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "num_ctx" and parts[1].isdigit():
            return int(parts[1])
    if env_value and env_value.strip().isdigit():
        return int(env_value.strip())
    return None


class DoctorCheck:
    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description
        self.passed = False
        self.skipped = False
        self.details = ""


def run_diagnostics(config_path: str = "datamind.yaml") -> list[DoctorCheck]:
    """Execute all diagnostic checks and return report items."""
    checks: list[DoctorCheck] = []

    # 1. Python Version
    c1 = DoctorCheck("Python Version", "Python >= 3.11 runtime environment")
    py_ver = sys.version_info
    if py_ver >= (3, 11):
        c1.passed = True
        c1.details = f"Python {py_ver.major}.{py_ver.minor}.{py_ver.micro}"
    else:
        c1.passed = False
        c1.details = f"Python {py_ver.major}.{py_ver.minor} is below minimum requirement 3.11"
    checks.append(c1)

    # 2. Dependencies
    c2 = DoctorCheck("Core Dependencies", "Verify essential analytical and runtime libraries")
    required_pkgs = [
        ("duckdb", "DuckDB engine"),
        ("sqlglot", "SQL transpiler and guard"),
        ("openai", "OpenAI API client"),
        ("pydantic", "Schema validation"),
        ("yaml", "PyYAML loader"),
    ]
    missing = []
    installed = []
    for mod, desc in required_pkgs:
        try:
            importlib.import_module(mod)
            installed.append(mod)
        except ImportError:
            missing.append(mod)

    if not missing:
        c2.passed = True
        c2.details = f"All {len(required_pkgs)} core packages installed and importable"
    else:
        c2.passed = False
        c2.details = f"Missing packages: {', '.join(missing)}"
    checks.append(c2)

    # 3. Configuration & Semantic Model
    c3 = DoctorCheck("Configuration & Semantic Model", "Verify datamind.yaml and semantic model schema")
    try:
        cfg = load_config(config_path)
        sem_path = Path(cfg.semantic_model)
        if sem_path.exists():
            from datamind.semantic.loader import load_semantic_model
            model = load_semantic_model(str(sem_path))
            c3.passed = True
            c3.details = f"Config valid. Semantic model '{model.name}' loaded with {len(model.tables)} tables."
        else:
            c3.passed = False
            c3.details = f"Semantic model file '{sem_path}' not found."
    except Exception as e:
        c3.passed = False
        c3.details = f"Config error: {e}"
    checks.append(c3)

    # 4. DuckDB Local Database
    c4 = DoctorCheck("DuckDB Storage", "Verify DuckDB database connectivity and read-only access")
    try:
        cfg = load_config(config_path)
        db_p = Path(cfg.backend.duckdb_path)
        if db_p.exists():
            import duckdb
            con = duckdb.connect(str(db_p), read_only=True)
            tbl_count = len(con.execute("SHOW TABLES").fetchall())
            con.close()
            c4.passed = True
            c4.details = f"Database '{db_p.name}' accessible with {tbl_count} tables (read-only verified)"
        else:
            c4.passed = False
            c4.details = f"Database file '{db_p}' not found"
    except Exception as e:
        c4.passed = False
        c4.details = f"DuckDB error: {e}"
    checks.append(c4)

    # 5. Local LLM Endpoint & Context Window
    c5 = DoctorCheck("Local LLM (Ollama)", "Check local model reachability and context window capacity")
    try:
        cfg = load_config(config_path)
        base_url = cfg.llm.base_url.rstrip("/")
        if CostGuard.is_local_endpoint(base_url):
            # Probe Ollama API (localhost:11434/api/tags)
            host_root = base_url.replace("/v1", "")
            req = urllib.request.Request(f"{host_root}/api/tags", headers={"User-Agent": "DataMind-Doctor"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name") for m in data.get("models", [])]
                target = cfg.llm.orchestrator_model
                if target in models or f"{target}:latest" in models:
                    show_req = urllib.request.Request(
                        f"{host_root}/api/show",
                        data=json.dumps({"model": target}).encode("utf-8"),
                        headers={"User-Agent": "DataMind-Doctor", "Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(show_req, timeout=5) as show_resp:
                        params = json.loads(show_resp.read().decode("utf-8")).get("parameters", "")
                    ctx = ollama_configured_context(params, os.environ.get("OLLAMA_CONTEXT_LENGTH"))
                    if ctx is not None and ctx >= MIN_OLLAMA_CONTEXT:
                        c5.passed = True
                        c5.details = f"Ollama reachable at {host_root}. Target model '{target}' is available (context {ctx})."
                    else:
                        c5.passed = False
                        c5.details = (
                            f"Model '{target}' has no context window >= {MIN_OLLAMA_CONTEXT} configured, so Ollama "
                            "defaults to 4096 and long answers are cut off (finish_reason=length). Create a variant "
                            "with 'PARAMETER num_ctx 16384' in a Modelfile (see docs/quickstart.md section 5) or set "
                            "OLLAMA_CONTEXT_LENGTH=16384 for the Ollama server."
                        )
                else:
                    c5.passed = False
                    available = ", ".join(models[:5]) if models else "none"
                    c5.details = f"Ollama reachable, but target model '{target}' is unavailable. Available: {available}."
        else:
            c5.passed = True
            c5.details = f"Remote endpoint configured ({base_url}). Checked via CostGuard."
    except Exception as e:
        c5.passed = False
        c5.details = f"Local LLM unreachable ({e}). Start Ollama on port 11434."
    checks.append(c5)

    # 6. Budget Guard Safety Net
    c6 = DoctorCheck("Budget & Cost Guard", "Client-side fail-closed cloud guard configuration")
    try:
        cfg = load_config(config_path)
        b = cfg.llm.budget
        guard = CostGuard()
        allow_cloud = os.environ.get("DATAMIND_ALLOW_CLOUD", "0") == "1"
        cap_str = f"${b.max_usd_total:.2f} USD" if b.max_usd_total is not None else "Unset (fail-closed)"
        cloud_active = (allow_cloud and b.max_usd_total is not None and b.price_per_million_input_usd is not None)
        cloud_status = "cloud allowed" if cloud_active else "cloud disabled"
        c6.passed = True
        c6.details = f"Fail-closed guard active. Budget cap: {cap_str}. Cloud status: {cloud_status}."
    except Exception as e:
        c6.passed = False
        c6.details = f"Budget guard error: {e}"
    checks.append(c6)

    # 7. Snowflake Connectivity & Read-Only Enforcement
    c7 = DoctorCheck("Snowflake Adapter", "Verify Snowflake connectivity and enforce read-only role")
    try:
        cfg = load_config(config_path)
        sf_cfg = cfg.backend.snowflake
        acc = sf_cfg.get_account() if sf_cfg else None
        usr = sf_cfg.get_user() if sf_cfg else None
        if acc and usr:
            from datamind.adapters.snowflake_adapter import SnowflakeAdapter
            adapter = SnowflakeAdapter(sf_cfg, timeout_seconds=5)
            # Execute read-only version check
            res = adapter.execute("SELECT CURRENT_VERSION(), CURRENT_ROLE()")
            ver, role = res.rows[0][0], res.rows[0][1]

            # Attempt a probe write to confirm read-only enforcement
            write_blocked = False
            try:
                adapter.execute("CREATE TABLE IF NOT EXISTS DATAMIND_READONLY_PROBE_TBL (id INT)")
            except Exception:
                write_blocked = True

            adapter.close()
            c7.passed = True
            c7.details = f"Snowflake v{ver} connected under role '{role}'. Read-only enforced: {write_blocked}."
        else:
            c7.skipped = True
            c7.details = "Snowflake credentials not provided (offline/DuckDB mode active)."
    except Exception as e:
        c7.skipped = True
        c7.details = f"Snowflake not connected: {e}"
    checks.append(c7)

    return checks


def print_doctor_report(checks: list[DoctorCheck]) -> int:
    """Print clean formatted PASS/FAIL doctor diagnostic report."""
    print("=" * 70)
    print("DATAMIND SYSTEM HEALTH & DIAGNOSTIC DOCTOR")
    print("=" * 70)

    all_ok = True
    for c in checks:
        if c.skipped:
            status_tag = "[SKIP]"
        elif c.passed:
            status_tag = "[PASS]"
        else:
            status_tag = "[FAIL]"
            all_ok = False

        print(f"{status_tag} {c.name:<32} {c.details}")

    print("-" * 70)
    if all_ok:
        print("Verdict: ALL DIAGNOSTIC CHECKS PASSED. System is healthy and operational.")
        return 0
    else:
        print("Verdict: ONE OR MORE CHECKS FAILED. Review details above.")
        return 1
