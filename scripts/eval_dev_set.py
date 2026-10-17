"""Runner script for Olist Dev Set evaluation and ablation."""

import sys
from pathlib import Path
from datamind.eval.runner import run_evaluation
from datamind.eval.ledger import RunLedger


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else "datamind_olist.yaml"
    suite = sys.argv[2] if len(sys.argv) > 2 else "olist_dev"

    print(f"Starting evaluation of suite '{suite}' with config '{config_path}'...")
    rep = run_evaluation(
        suite=suite,
        config_path=config_path,
        save_results=True,
        provider="local",
        use_cache=False,
    )
    print("\n" + "=" * 70)
    print(f"EVALUATION COMPLETE: {rep.passed}/{rep.total} Passed ({rep.pass_rate_pct}%)")
    print(f"Silent Wrong:        {rep.silent_wrong_count}")
    print(f"First Attempt:       {rep.first_attempt_passes}")
    print("=" * 70)


if __name__ == "__main__":
    main()
