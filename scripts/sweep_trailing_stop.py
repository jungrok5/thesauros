"""Trailing-stop sweep + combined (stop-loss + trailing) sweep.

Uses cached universe fires CSV. Tests:
  - Trailing-only: 5/7/10/12/15/20%
  - Combined SL=10% + Trail=X% for X in 10/15/20

Run AFTER scripts/sweep_stop_loss.py completes.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


TRAIL_VALUES = [0.05, 0.07, 0.10, 0.12, 0.15, 0.20]
COMBINED = [(0.10, 0.10), (0.10, 0.15), (0.10, 0.20)]


def _run(label: str, sl: float, ts: float, fires_csv: Path, repo: Path) -> None:
    print(f"=== {label} ===", flush=True)
    cmd = [
        sys.executable, "-m", "app.backtest.portfolio",
        "--start", "2009-01-01", "--end", "2026-05-22",
        "--hold-weeks", "24",
        "--max-positions", "20",
        "--initial-cash", "10000000",
        "--fires-csv", str(fires_csv),
        "--stop-loss-pct", str(sl),
        "--trailing-stop-pct", str(ts),
        "--metrics",
    ]
    result = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR: rc={result.returncode}", flush=True)
        print(result.stderr[-2000:], flush=True)
        return
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


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    fires_csv = repo / "data" / "sweep_100_24w.csv"
    if not fires_csv.exists():
        print(f"missing fires CSV: {fires_csv}", file=sys.stderr)
        return 1

    print("### Trailing-stop only", flush=True)
    for ts in TRAIL_VALUES:
        _run(f"TS = {ts}", sl=0.0, ts=ts, fires_csv=fires_csv, repo=repo)

    print("\n### Combined SL + Trailing", flush=True)
    for sl, ts in COMBINED:
        _run(f"SL = {sl}, TS = {ts}", sl=sl, ts=ts, fires_csv=fires_csv, repo=repo)

    return 0


if __name__ == "__main__":
    sys.exit(main())
