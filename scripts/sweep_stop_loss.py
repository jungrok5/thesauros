"""Tighter stop-loss sweep around the 10% finding.

Re-uses the universe fires CSV (data/sweep_all_17yr.csv) to avoid
the 4-hour walk. Just re-runs the portfolio sim for each SL value
and prints summary metrics.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SL_VALUES = [0.0, 0.05, 0.07, 0.10, 0.12, 0.15, 0.20]


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    # Use 24w 100-ticker fires (matches the best hold-weeks finding +
    # was the baseline of the previous SL sweep).
    fires_csv = repo / "data" / "sweep_100_24w.csv"
    if not fires_csv.exists():
        print(f"missing fires CSV: {fires_csv}", file=sys.stderr)
        return 1

    for sl in SL_VALUES:
        print(f"=== SL = {sl} ===", flush=True)
        cmd = [
            sys.executable, "-m", "app.backtest.portfolio",
            "--start", "2009-01-01", "--end", "2026-05-22",
            "--hold-weeks", "24",
            "--max-positions", "20",
            "--initial-cash", "10000000",
            "--fires-csv", str(fires_csv),
            "--stop-loss-pct", str(sl),
            "--metrics",
        ]
        result = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ERROR: rc={result.returncode}", flush=True)
            print(result.stderr[-2000:], flush=True)
            continue
        out = result.stdout
        keepers = [
            "total_return_pct",
            "annualised_return_pct",
            "max_drawdown_mtm_pct",
            "sharpe", "sortino", "calmar", "payoff",
        ]
        for line in out.splitlines():
            for k in keepers:
                if k in line and ("%" in line or "." in line.split()[-1]):
                    print(" ", line.strip(), flush=True)
                    break
    return 0


if __name__ == "__main__":
    sys.exit(main())
