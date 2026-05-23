"""Universe sweep: every ticker × every fired signal, one walk per ticker.

Phase 3 of the backtest framework. Where `single_signal` tested ONE
(ticker, signal) pair, this iterates the whole KR universe (or a
sample) and aggregates results by signal_type.

Key optimization: walk each ticker ONCE, collect ALL signals fired at
each candidate bar in one pass. Re-walking for each signal would be
N times more expensive.

Output:
  - Per-fire CSV (one row per fire) — full raw data for follow-up.
  - Per-signal aggregate (n_fires, win_rate, avg_return, payoff, best
    ticker per signal). Printed to stdout, also saveable.

Usage:
    python -m app.backtest.sweep --sample 10 --hold-weeks 8
    python -m app.backtest.sweep --market KOSPI --limit 100 \\
        --hold-weeks 8 --csv sweep_kospi100.csv
    python -m app.backtest.sweep --tickers 005930.KS 035720.KS

PIT safety: same as single_signal — at each candidate bar i the
analyzer only sees df[:i+1].
"""
from __future__ import annotations

import argparse
import csv
import logging
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.book.analyzer import analyze_ticker      # noqa: E402
from app.db import get_conn                       # noqa: E402
from app.db.scan_daily import _list_tickers, extract_signals  # noqa: E402
from app.backtest.single_signal import (          # noqa: E402
    _MIN_BARS, load_weekly_bars,
)

log = logging.getLogger("backtest.sweep")


# Map signal_type → direction so we can invert the forward return for
# bearish signals (a SELL signal "wins" when price subsequently drops).
# Action signals don't carry direction in their params; pattern signals
# do (params["direction"]), but we double-derive here for consistency.
_BEARISH_ACTION_SIGNALS = {
    "action_sell", "action_sell_short", "action_avoid",
}
_BEARISH_PATTERN_SUFFIXES = (
    "double_top", "triple_top", "head_and_shoulders",
    "death_messenger", "rounding_top",
)


def signal_direction(signal_type: str, params_direction: str = "") -> str:
    """Return 'bullish' | 'bearish' | 'neutral' for a signal_type.

    Order: (1) params direction if explicit, (2) signal_type rules.
    """
    if params_direction in ("bullish", "bearish", "neutral"):
        return params_direction
    if signal_type in _BEARISH_ACTION_SIGNALS:
        return "bearish"
    if signal_type.startswith("action_buy") or signal_type.startswith("action_strong"):
        return "bullish"
    if signal_type.startswith("pattern_"):
        # Inverse H&S is bullish despite "head_and_shoulders" substring.
        # Same idea would apply to any future "inverse_*" pattern of a
        # bearish base type.
        if signal_type.startswith("pattern_inverse_"):
            return "bullish"
        for suffix in _BEARISH_PATTERN_SUFFIXES:
            if suffix in signal_type:
                return "bearish"
        return "bullish"
    return "neutral"


def effective_return(return_pct: float, direction: str) -> float:
    """For bearish signals, invert the raw forward return so 'win'
    means 'price went DOWN as the signal predicted'. For bullish /
    neutral, keep as-is."""
    if direction == "bearish":
        return -return_pct
    return return_pct


def walk_ticker_collect_fires(
    ticker: str, hold_weeks: int,
) -> List[Dict[str, Any]]:
    """Walk all weekly bars of one ticker, collecting EVERY signal
    that fires at each bar with its forward N-week return.

    Returns: list of fire records (one per (bar, signal) pair).
    Returns [] if the ticker has no bars or insufficient history.

    Note: clears the global find_swings cache before each ticker to
    prevent unbounded growth across long sweeps (each ticker has its
    own pit_df identities; stale entries from prior tickers waste
    memory but don't affect correctness).
    """
    from app.book._swings import clear_swings_cache
    clear_swings_cache()

    df = load_weekly_bars(ticker)
    if df.empty or len(df) < _MIN_BARS + hold_weeks:
        return []

    fires: List[Dict[str, Any]] = []
    last_eligible_i = len(df) - hold_weeks - 1
    for i in range(_MIN_BARS, last_eligible_i + 1):
        bar_dt = df.iloc[i]["date"].date()
        pit_df = df.iloc[: i + 1].copy()
        pit_df.attrs["grain"] = "W"
        try:
            result = analyze_ticker(ticker, pit_df, weekly=True, monthly=True)
        except Exception as e:
            log.debug("analyze fail %s @ %s: %s", ticker, bar_dt, e)
            continue
        signals = extract_signals(result)
        if not signals:
            continue
        entry_price = float(df.iloc[i]["close"])
        if entry_price <= 0:
            continue
        exit_idx = i + hold_weeks
        exit_price = float(df.iloc[exit_idx]["close"])
        ret = (exit_price / entry_price - 1.0) * 100.0
        for s in signals:
            sig = s.get("signal_type", "?")
            params_dir = s.get("params", {}).get("direction", "")
            direction = signal_direction(sig, params_dir)
            fires.append({
                "ticker": ticker,
                "signal_type": sig,
                "direction": direction,
                "timeframe": s.get("timeframe", ""),
                "strength": float(s.get("strength", 0.0)),
                "entry_date": bar_dt.isoformat(),
                "entry_price": entry_price,
                "exit_date": df.iloc[exit_idx]["date"].date().isoformat(),
                "exit_price": exit_price,
                "return_pct": ret,
                "effective_return_pct": effective_return(ret, direction),
                "hold_weeks": hold_weeks,
            })
    return fires


def aggregate_by_signal(
    fires: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Aggregate per-signal_type stats. Returns one row per signal,
    sorted by n_fires desc. Each row: signal_type, n, win_rate,
    avg/median/best/worst return, payoff, best_ticker (single most
    profitable fire's ticker)."""
    by_sig: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for f in fires:
        by_sig[f["signal_type"]].append(f)

    out: List[Dict[str, Any]] = []
    for sig, group in by_sig.items():
        # Use EFFECTIVE return (inverted for bearish) so win_rate /
        # payoff are interpretable uniformly: "how often did the signal
        # correctly predict the price direction".
        rets = [g["effective_return_pct"] for g in group]
        wins = [r for r in rets if r > 0]
        losses = [r for r in rets if r <= 0]
        best_fire = max(group, key=lambda g: g["effective_return_pct"])
        avg_win = statistics.mean(wins) if wins else 0.0
        avg_loss = statistics.mean(losses) if losses else 0.0
        # Direction tag for display (all fires of one signal_type share it).
        direction = group[0].get("direction", "neutral")
        out.append({
            "signal_type": sig,
            "direction": direction,
            "n_fires": len(group),
            "n_tickers": len({g["ticker"] for g in group}),
            "win_rate": len(wins) / len(rets) if rets else 0.0,
            "avg_return_pct": statistics.mean(rets) if rets else 0.0,
            "median_return_pct": statistics.median(rets) if rets else 0.0,
            "best_pct": max(rets) if rets else 0.0,
            "worst_pct": min(rets) if rets else 0.0,
            "avg_win_pct": avg_win,
            "avg_loss_pct": avg_loss,
            "payoff": (avg_win / abs(avg_loss)) if wins and losses else None,
            "best_ticker": best_fire["ticker"],
            "best_entry": best_fire["entry_date"],
        })
    out.sort(key=lambda r: r["n_fires"], reverse=True)
    return out


def aggregate_top_per_signal(
    fires: Sequence[Dict[str, Any]], top_n: int = 5,
) -> Dict[str, List[Dict[str, Any]]]:
    """For each signal_type, return the top-N highest effective-return
    fires. For bearish signals, top = biggest price drops the signal
    correctly predicted."""
    by_sig: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for f in fires:
        by_sig[f["signal_type"]].append(f)
    out: Dict[str, List[Dict[str, Any]]] = {}
    for sig, group in by_sig.items():
        group_sorted = sorted(group, key=lambda g: g["effective_return_pct"],
                              reverse=True)
        out[sig] = group_sorted[:top_n]
    return out


def _print_leaderboard(agg: List[Dict[str, Any]],
                       min_fires: int = 5) -> None:
    """Pretty-print per-signal aggregate. Signals with < min_fires
    suppressed to noise (anything less than ~5 fires across the
    universe is statistically meaningless). Stats based on EFFECTIVE
    return (raw return for bullish, inverted for bearish), so a high
    win-rate on a bearish signal means it correctly predicted drops."""
    print()
    print("=" * 100)
    print(f"{'signal_type':30s} {'dir':>4s} {'n_fires':>8s} {'n_tic':>6s} "
          f"{'win%':>6s} {'avg%':>7s} {'payoff':>7s} {'best%':>7s} "
          f"{'best_ticker':>14s}")
    print("-" * 100)
    for row in agg:
        if row["n_fires"] < min_fires:
            continue
        payoff_str = (f"{row['payoff']:.2f}" if row["payoff"] is not None
                      else "  -")
        dir_short = {"bullish": "↑", "bearish": "↓", "neutral": "·"}.get(
            row.get("direction", "neutral"), "?"
        )
        print(
            f"{row['signal_type']:30s} {dir_short:>4s} {row['n_fires']:>8d} "
            f"{row['n_tickers']:>6d} {row['win_rate']*100:>5.1f}% "
            f"{row['avg_return_pct']:>+6.2f}% {payoff_str:>7s} "
            f"{row['best_pct']:>+6.1f}% {row['best_ticker']:>14s}"
        )
    print("=" * 100)


def _print_top_fires(top: Dict[str, List[Dict[str, Any]]],
                     signals_filter: Optional[List[str]] = None) -> None:
    """Pretty-print top-N fires per signal. Displays raw return_pct
    AND effective_return_pct so the direction-correction is visible
    (bearish signals show negative raw but positive effective)."""
    for sig in sorted(top.keys()):
        if signals_filter and sig not in signals_filter:
            continue
        if not top[sig]:
            continue
        direction = top[sig][0].get("direction", "neutral")
        dir_label = {"bullish": "↑bull", "bearish": "↓bear",
                     "neutral": "·neut"}.get(direction, "?")
        print()
        print(f"--- top fires: {sig} ({dir_label}) ---")
        for f in top[sig]:
            print(
                f"  {f['ticker']:>14s}  {f['entry_date']} → {f['exit_date']}  "
                f"{f['entry_price']:>9.0f} → {f['exit_price']:>9.0f}  "
                f"(raw {f['return_pct']:+.1f}%, eff {f['effective_return_pct']:+.1f}%, "
                f"hold {f['hold_weeks']}w)"
            )


def _resolve_tickers(args: argparse.Namespace) -> List[str]:
    """Apply --tickers / --market / --limit / --sample to produce the
    final ticker list."""
    if args.tickers:
        return list(args.tickers)
    markets = [args.market] if args.market else ["KOSPI", "KOSDAQ"]
    tickers = _list_tickers(markets=markets, limit=args.limit)
    if args.sample:
        import random
        random.seed(args.sample_seed)
        tickers = random.sample(tickers, min(args.sample, len(tickers)))
        tickers.sort()
    return tickers


def _walk_one_for_pool(args: Tuple[str, int]) -> List[Dict[str, Any]]:
    """ProcessPoolExecutor worker — returns fires or empty list on
    error. Each worker has its own analyzer cache state."""
    ticker, hold_weeks = args
    try:
        return walk_ticker_collect_fires(ticker, hold_weeks)
    except Exception as e:
        log.warning("ticker %s failed: %s", ticker, e)
        return []


def _parallel_walk(
    tickers: List[str], hold_weeks: int, workers: int, t0: float,
) -> List[Dict[str, Any]]:
    """Run walk_ticker_collect_fires across `workers` processes.

    Result determinism: we collect fires PER ticker (each worker's
    output preserves the bar-by-bar order for that ticker), then
    sort by ticker name + entry_date to produce a fully-deterministic
    final list — same content as serial walk, just faster.
    """
    from concurrent.futures import ProcessPoolExecutor, as_completed

    by_ticker: Dict[str, List[Dict[str, Any]]] = {}
    completed = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_walk_one_for_pool, (t, hold_weeks)): t
            for t in tickers
        }
        for fut in as_completed(futures):
            t = futures[fut]
            by_ticker[t] = fut.result()
            completed += 1
            if completed % 20 == 0 or completed == len(tickers):
                elapsed = time.time() - t0
                rate = completed / elapsed if elapsed > 0 else 0
                remain = (len(tickers) - completed) / rate if rate > 0 else 0
                total_fires = sum(len(v) for v in by_ticker.values())
                log.info("[%d/%d] %s — %.0fs elapsed, %d fires so far, ~%.0fs remain",
                         completed, len(tickers), t, elapsed, total_fires, remain)

    # Preserve INPUT ticker order so parallel output is bit-identical
    # to serial. Sorting by ticker name would diverge from serial which
    # iterates in user-supplied order.
    all_fires: List[Dict[str, Any]] = []
    for t in tickers:
        if t in by_ticker:
            all_fires.extend(by_ticker[t])
    return all_fires


def _save_csv(fires: List[Dict[str, Any]], path: Path) -> None:
    if not fires:
        log.warning("no fires to write to %s", path)
        return
    fieldnames = list(fires[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(fires)
    log.info("wrote %d fires to %s", len(fires), path)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--tickers", nargs="+", default=None,
                   help="explicit ticker list (overrides market/sample)")
    g.add_argument("--sample", type=int, default=None,
                   help="random sample size from KOSPI+KOSDAQ")
    p.add_argument("--sample-seed", type=int, default=42)
    p.add_argument("--market", default=None,
                   help="KOSPI or KOSDAQ (default: both)")
    p.add_argument("--limit", type=int, default=None,
                   help="cap ticker count (after market filter, before sample)")
    p.add_argument("--hold-weeks", type=int, default=8,
                   help="exit N weeks after entry (default 8)")
    p.add_argument("--min-fires", type=int, default=5,
                   help="hide signals with < N fires from leaderboard")
    p.add_argument("--top-fires", type=int, default=5,
                   help="show top-N most-profitable fires per signal")
    p.add_argument("--csv", default=None,
                   help="write per-fire CSV to this path")
    p.add_argument("--filter-signal", nargs="+", default=None,
                   help="only show top fires for these signals (substring match)")
    p.add_argument("--workers", type=int, default=1,
                   help="parallelize ticker walks via ProcessPoolExecutor "
                        "(N processes). Each worker has its own analyzer "
                        "caches — deterministic outputs verified by "
                        "test_sweep_parallel_parity. Default 1 (serial).")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    tickers = _resolve_tickers(args)
    log.info("walking %d ticker(s), hold_weeks=%d", len(tickers), args.hold_weeks)

    all_fires: List[Dict[str, Any]] = []
    t0 = time.time()
    if args.workers > 1:
        log.info("parallel mode: %d workers", args.workers)
        all_fires = _parallel_walk(tickers, args.hold_weeks, args.workers, t0)
    else:
        for j, t in enumerate(tickers, start=1):
            if j % 20 == 0 or j == len(tickers):
                elapsed = time.time() - t0
                rate = j / elapsed if elapsed > 0 else 0
                remain = (len(tickers) - j) / rate if rate > 0 else 0
                log.info("[%d/%d] %s — %.1fs elapsed, %d fires so far, ~%.0fs remain",
                         j, len(tickers), t, elapsed, len(all_fires), remain)
            try:
                fires = walk_ticker_collect_fires(t, hold_weeks=args.hold_weeks)
            except Exception as e:
                log.warning("ticker %s failed: %s", t, e)
                continue
            all_fires.extend(fires)

    if args.csv:
        _save_csv(all_fires, Path(args.csv))

    agg = aggregate_by_signal(all_fires)
    _print_leaderboard(agg, min_fires=args.min_fires)

    if args.top_fires > 0:
        top = aggregate_top_per_signal(all_fires, top_n=args.top_fires)
        _print_top_fires(top, signals_filter=args.filter_signal)

    return 0


if __name__ == "__main__":
    sys.exit(main())
