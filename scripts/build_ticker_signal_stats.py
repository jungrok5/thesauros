"""Pre-compute per-ticker book signal stats from sweep_all_17yr.csv.

Reads the 472MB fires CSV (8w hold, full universe), aggregates by
(ticker, signal_type) → n_fires + avg_return + win_rate + median_return.
Dumps to web-next/public/ticker-signal-stats/{ticker}.json so each
detail page loads only its own slice (~1KB) instead of a 1.5MB index.

Each row is a fire = one historical entry detection. Returns are the
actual price-based 8w-forward result. So this is "if you'd taken every
fire of this signal on this ticker over 17yr, here's the average
outcome" — a backward-looking quality marker.

JSON shape (single file web-next/public/ticker-signal-stats.json):
{
  "005930.KS": {
    "action_strong_buy":  {"n": 12, "avg_pct": 8.3, "win_pct": 75, "median_pct": 6.4},
    "volume_case_3":      {"n": 8,  "avg_pct": 12.1, "win_pct": 87, "median_pct": 11.0}
  },
  ...
}
Server component loads + caches in module-level var, filters per ticker.
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


# Only emit stats for these "top-5 + book honorable mentions". Keeps the
# JSON small and the UI compact.
KEEPER_SIGNALS = frozenset([
    "volume_case_3", "pattern_forking", "volume_case_7",
    "action_strong_buy", "pattern_ma240_breakout",
    "action_buy", "pattern_double_bottom", "pattern_triple_bottom",
    "volume_case_12", "pattern_catalyst_candle", "pattern_doulbanji",
    "pattern_inverse_head_and_shoulders", "pattern_rounding_bottom",
])


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    src = repo / "data" / "sweep_all_17yr.csv"
    dst = repo / "web-next" / "public" / "ticker-signal-stats.json"
    if not src.exists():
        print(f"missing: {src}", file=sys.stderr)
        return 1

    # In-memory bucket: ticker → signal → [return_pct, ...]
    buckets: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list),
    )

    with src.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        n_rows = 0
        for row in reader:
            n_rows += 1
            sig = row["signal_type"]
            if sig not in KEEPER_SIGNALS:
                continue
            try:
                ret = float(row["effective_return_pct"])
            except (ValueError, TypeError):
                continue
            buckets[row["ticker"]][sig].append(ret)

    out: dict[str, dict[str, dict]] = {}
    for ticker, sigs in buckets.items():
        ticker_out: dict[str, dict] = {}
        for sig, rets in sigs.items():
            if len(rets) < 3:        # too few fires for stats
                continue
            wins = sum(1 for r in rets if r > 0)
            ticker_out[sig] = {
                "n": len(rets),
                "avg_pct": round(statistics.mean(rets), 2),
                "win_pct": round(wins / len(rets) * 100, 1),
                "median_pct": round(statistics.median(rets), 2),
            }
        if ticker_out:
            out[ticker] = ticker_out

    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)

    size_kb = dst.stat().st_size / 1024
    print(f"  rows scanned: {n_rows:,}", flush=True)
    print(f"  tickers w/ stats: {len(out):,}", flush=True)
    print(f"  written: {dst} ({size_kb:.1f} KB)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
