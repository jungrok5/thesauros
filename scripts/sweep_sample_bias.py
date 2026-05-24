"""Sample-bias check.

Re-run the SL × max sweep on 3 additional random 100-ticker samples
(seeds 100/200/300) to confirm the SL=3%/max=5 = +9257% and
SL=10%/max=8 = +6380% wins aren't lucky-sample artifacts.

Walk for each seed uses sweep --workers 8 (≈6 min per sample).
Then run 5 configs per seed × 4 seeds = 20 sims (each ~5 sec).
"""
from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path


SEEDS = [42, 100, 200, 300]   # 42 = existing baseline
CONFIGS = [
    # (label, stop_loss_pct, max_positions)
    ("no-SL/max=20",        0.00, 20),
    ("SL=3%/max=5",         0.03, 5),
    ("SL=5%/max=8",         0.05, 8),
    ("SL=5%/max=10",        0.05, 10),
    ("SL=10%/max=8",        0.10, 8),
]


def walk_seed(seed: int, repo: Path) -> Path:
    csv_path = repo / "data" / f"sweep_100_seed{seed}_24w.csv"
    if csv_path.exists():
        print(f"  seed={seed} CSV already exists, skipping walk", flush=True)
        return csv_path
    print(f"  seed={seed} walking 100 tickers × 24w (workers=8)...", flush=True)
    cmd = [
        sys.executable, "-m", "app.backtest.sweep",
        "--sample", "100", "--sample-seed", str(seed),
        "--hold-weeks", "24", "--workers", "8",
        "--csv", str(csv_path),
    ]
    result = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR rc={result.returncode}", flush=True)
        print(result.stderr[-1500:], flush=True)
        raise SystemExit(1)
    return csv_path


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    from app.backtest import portfolio as P
    from app.backtest.metrics import compute_full_metrics

    # 42 maps to existing sweep_100_24w.csv (same content).
    existing = repo / "data" / "sweep_100_24w.csv"
    if existing.exists():
        compat = repo / "data" / "sweep_100_seed42_24w.csv"
        if not compat.exists():
            import shutil
            shutil.copyfile(existing, compat)

    print("# Walking samples...", flush=True)
    csvs = {}
    for seed in SEEDS:
        csvs[seed] = walk_seed(seed, repo)

    print("\n# Running 5 configs × 4 seeds:\n", flush=True)
    start = date(2009, 1, 1)
    end = date(2026, 5, 22)

    # Compact table: rows = configs, cols = seeds
    rows = []
    for label, sl, mp in CONFIGS:
        row = [label]
        for seed in SEEDS:
            fires = P.load_fires_csv(csvs[seed])
            cands = P.filter_entry_fires(fires, P.DEFAULT_ENTRY_SIGNALS)
            state = P.simulate(
                cands, start, end,
                initial_cash=10_000_000.0,
                max_positions=mp,
                stop_loss_pct=sl,
            )
            m = compute_full_metrics(state, start, end)
            row.append(f"{m['total_return_pct']:+8.0f}%")
        rows.append(row)

    # Print
    header = f"{'config':<20s}  " + "  ".join(f"seed={s:>4}" for s in SEEDS)
    print(header, flush=True)
    print("-" * len(header), flush=True)
    for r in rows:
        print(f"{r[0]:<20s}  " + "  ".join(f"{v:>10s}" for v in r[1:]),
              flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
