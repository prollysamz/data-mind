"""Append-only evaluation run ledger for DataMind.

Maintains an immutable record of all benchmark runs, ablations, model tests,
and audit metrics in eval/run_ledger.jsonl.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def get_ledger_path() -> Path:
    return Path(os.getenv("DATAMIND_RUN_LEDGER_PATH", "eval/run_ledger.jsonl"))

LEDGER_PATH = Path("eval/run_ledger.jsonl")


def compute_file_sha256(path: str | Path) -> str:
    """Compute hex SHA-256 hash of a file's raw bytes."""
    p = Path(path)
    if not p.exists():
        return ""
    return hashlib.sha256(p.read_bytes()).hexdigest()


def get_git_commit_hash() -> str:
    """Get current git commit hash (short)."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "uncommitted"


@dataclass
class LedgerEntry:
    run_id: str
    timestamp: str
    git_commit: str
    suite_name: str
    question_set_hash: str
    config_hash: str
    flags: dict[str, Any]
    model: str
    backend: str
    total: int
    passed: int
    failed: int
    not_run: int
    pass_rate_pct: float
    silent_wrong_count: int = 0
    first_attempt_passes: int = 0
    repair_passes: int = 0
    median_latency_ms: float = 0.0
    p90_latency_ms: float = 0.0
    total_calls: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RunLedger:
    """Manages appending and reading records from eval/run_ledger.jsonl."""

    def __init__(self, ledger_path: Path | str | None = None) -> None:
        self.ledger_path = Path(ledger_path) if ledger_path else get_ledger_path()
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

    def record_run(self, entry: LedgerEntry) -> None:
        """Append an immutable run record to the ledger."""
        with open(self.ledger_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict()) + "\n")

    def get_runs(self, suite_name: str | None = None) -> list[dict[str, Any]]:
        """Retrieve all recorded runs, optionally filtered by suite name."""
        if not self.ledger_path.exists():
            return []
        runs = []
        with open(self.ledger_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if suite_name is None or data.get("suite_name") == suite_name:
                        runs.append(data)
                except json.JSONDecodeError:
                    continue
        return runs

    def generate_ablation_markdown(self, suite_name: str = "olist_dev") -> str:
        """Generate markdown ablation comparison table directly from ledger records."""
        runs = self.get_runs(suite_name=suite_name)
        if not runs:
            return f"No ledger runs found for suite '{suite_name}'."

        lines = [
            f"### Dev Set Technique Ablation Table ({suite_name})",
            "",
            "| Run ID | Commit | Model | Flags / Technique | Passed / Total | Pass Rate | Silent Wrong | First Att. | Repaired | Med. Latency | Tokens | Cost USD |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]

        for r in runs:
            run_id = r.get("run_id", "")[:14]
            commit = r.get("git_commit", "")
            model = r.get("model", "").split(":")[-1]
            flags_dict = r.get("flags", {})
            active_flags = [k for k, v in flags_dict.items() if v]
            flags_str = ", ".join(active_flags) if active_flags else "Baseline (All OFF)"
            passed = r.get("passed", 0)
            total = r.get("total", 0)
            rate = f"{r.get('pass_rate_pct', 0.0):.1f}%"
            sw = r.get("silent_wrong_count", 0)
            first_att = r.get("first_attempt_passes", 0)
            rep = r.get("repair_passes", 0)
            lat = f"{r.get('median_latency_ms', 0.0):.0f}ms"
            tok = f"{r.get('total_tokens', 0):,}"
            cost = f"${r.get('estimated_cost_usd', 0.0):.4f}"

            lines.append(
                f"| `{run_id}` | `{commit}` | `{model}` | {flags_str} | {passed}/{total} | **{rate}** | {sw} | {first_att} | {rep} | {lat} | {tok} | {cost} |"
            )

        return "\n".join(lines)
