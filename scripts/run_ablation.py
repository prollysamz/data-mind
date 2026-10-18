"""Run ablation matrix across techniques on Olist Dev Set and record to ledger.

Techniques evaluated:
1. Baseline (All OFF)
2. Execution-Guided Repair (+EGR)
3. Schema Pruning (+SP)
4. Dynamic Few-Shot (+DFS, full stack)

Outputs ablation markdown table reading directly from eval/run_ledger.jsonl.
"""

from __future__ import annotations

import copy
from pathlib import Path
import sys
import time

from datamind.config import load_config
from datamind.eval.ledger import RunLedger
from datamind.eval.runner import run_evaluation


def run_ablation_matrix(config_path: str = "datamind_olist.yaml", max_items: int | None = None) -> str:
    print("=" * 80)
    print("DATAMIND WP-F2 DEV SET ABLATION MATRIX RUNNER")
    print("=" * 80)

    configurations = [
        {
            "name": "1. Baseline (All OFF)",
            "flags": {
                "schema_pruning": False,
                "dynamic_few_shot": False,
                "execution_guided_repair": False,
                "self_consistency": False,
            },
        },
        {
            "name": "2. + Execution-Guided Repair",
            "flags": {
                "schema_pruning": False,
                "dynamic_few_shot": False,
                "execution_guided_repair": True,
                "self_consistency": False,
            },
        },
        {
            "name": "3. + Schema Pruning",
            "flags": {
                "schema_pruning": True,
                "dynamic_few_shot": False,
                "execution_guided_repair": True,
                "self_consistency": False,
            },
        },
        {
            "name": "4. Full Stack (+ Dynamic Few-Shot)",
            "flags": {
                "schema_pruning": True,
                "dynamic_few_shot": True,
                "execution_guided_repair": True,
                "self_consistency": False,
            },
        },
    ]

    base_config = load_config(config_path)

    for cfg_spec in configurations:
        cfg_name = cfg_spec["name"]
        flags = cfg_spec["flags"]
        print(f"\n---> Running Ablation Configuration: {cfg_name}")

        active_config = copy.deepcopy(base_config)
        for k, v in flags.items():
            setattr(active_config.agent, k, v)

        # Temporary config file for runner provenance
        temp_cfg_path = Path(".datamind/temp_ablation_config.yaml")
        temp_cfg_path.parent.mkdir(parents=True, exist_ok=True)
        import yaml
        with open(temp_cfg_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(active_config.model_dump(), f)

        report = run_evaluation(
            suite="olist_dev",
            config_path=str(temp_cfg_path),
            save_results=True,
            provider="local",
            use_cache=False,
            max_items=max_items,
        )
        print(f"     Result: {report.passed}/{report.total} ({report.pass_rate_pct}%) | Silent Wrong: {report.silent_wrong_count} | 1st Attempt: {report.first_attempt_passes}")

    # Generate ablation table from ledger
    ledger = RunLedger()
    md_table = ledger.generate_ablation_markdown("olist_dev")
    print("\n" + "=" * 80)
    print("ABLATION RESULTS TABLE (GENERATED FROM RUN LEDGER)")
    print("=" * 80)
    print(md_table)
    print("=" * 80)
    return md_table


if __name__ == "__main__":
    cfg = sys.argv[1] if len(sys.argv) > 1 else "datamind_olist.yaml"
    max_q = int(sys.argv[2]) if len(sys.argv) > 2 else None
    run_ablation_matrix(cfg, max_items=max_q)
