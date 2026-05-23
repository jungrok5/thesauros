"""Sweep parallel-vs-serial parity.

ProcessPoolExecutor walks must produce bit-identical fires (after
sort by ticker + entry_date) compared to the serial path. Each
worker has its own analyzer cache state, so determinism depends on
analyze_ticker being deterministic + our sort being stable.

This test runs on 5 small tickers because spawning processes is
heavyweight; the cache_parity tests already cover deep within-walk
determinism.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_sweep(workers: int, tickers: list[str], tmp_csv: Path) -> int:
    """Spawn the sweep CLI as a subprocess so multiprocessing works
    cleanly (pickling needs __main__ context).
    """
    cmd = [
        sys.executable, "-m", "app.backtest.sweep",
        "--tickers", *tickers,
        "--hold-weeks", "8",
        "--top-fires", "0",
        "--csv", str(tmp_csv),
        "--workers", str(workers),
    ]
    env = os.environ.copy()
    env["BARS_SOURCE"] = "local"
    return subprocess.run(
        cmd, env=env, capture_output=True, text=True, timeout=600,
    ).returncode


def _read_csv_rows(path: Path) -> list[dict]:
    import csv
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[3] / "data" / "backtest.duckdb").exists(),
    reason="local DuckDB store not built — skip in CI without it",
)
def test_serial_vs_parallel_identical(tmp_path: Path) -> None:
    """4-ticker sweep, serial vs --workers 2. CSVs must be identical
    (same fires, same order, same values)."""
    tickers = ["005930.KS", "035720.KS", "000660.KS", "035420.KS"]
    serial_csv = tmp_path / "serial.csv"
    parallel_csv = tmp_path / "parallel.csv"

    rc1 = _run_sweep(1, tickers, serial_csv)
    assert rc1 == 0, f"serial sweep failed rc={rc1}"
    rc2 = _run_sweep(2, tickers, parallel_csv)
    assert rc2 == 0, f"parallel sweep failed rc={rc2}"

    rows_serial = _read_csv_rows(serial_csv)
    rows_parallel = _read_csv_rows(parallel_csv)

    assert len(rows_serial) == len(rows_parallel), (
        f"row count differs: serial={len(rows_serial)} "
        f"parallel={len(rows_parallel)}"
    )

    # Compare every row field-by-field (CSV values are strings —
    # string equality is exact).
    for i, (a, b) in enumerate(zip(rows_serial, rows_parallel)):
        if a != b:
            diffs = {k: (a[k], b[k]) for k in a if a[k] != b[k]}
            pytest.fail(
                f"row #{i} differs (ticker={a.get('ticker')}, "
                f"date={a.get('entry_date')}):\n  diffs: {diffs}"
            )
