"""Single-ticker × single-signal backtest (Phase 1 MVP).

Walks the weekly bars of one ticker, runs the analyzer at each
historical Friday close, and records the next-N-weeks return whenever
a given signal fires.

CLI:
    python -m app.backtest.single_signal 005930.KS --signal action_buy
    python -m app.backtest.single_signal 035720.KS --signal pattern_double_bottom --hold-weeks 12

PIT safety:
    The DataFrame passed to analyze_ticker() is sliced to bars on or
    before the candidate date. The analyzer reads no other data source
    (no live Naver fetch — removed in P_US). Verified by
    test_single_signal_backtest.py::test_pit_no_future_leak.

Cost model: NOT YET MODELED. Phase 3 (portfolio) will add KR transaction
    cost (0.18% sell fee + capital gains tax). MVP returns are raw
    close-to-close — interpret as "before friction".
"""
from __future__ import annotations

import argparse
import logging
import statistics
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.book.analyzer import analyze_ticker   # noqa: E402
from app.db import get_conn   # noqa: E402
from app.db.scan_daily import extract_signals  # noqa: E402

log = logging.getLogger("backtest.single_signal")


# Minimum bars needed before the first analyze call. The analyzer
# requires ~50 weekly bars (1 year) to compute its short MAs reliably.
# Below that the call returns "insufficient_history" so backtest skips.
_MIN_BARS = 50


def load_weekly_bars(ticker: str) -> pd.DataFrame:
    """Pull all weekly bars for one ticker.

    Source dispatch via `BARS_SOURCE` env var (or fallback chain):
      - "local" → DuckDB at data/backtest.duckdb (deep history, 2008-now)
      - "db"    → Supabase `bars` table (live, ~2y retention)
      - unset   → try local first; fall back to db if local empty/missing
                  (preserves CI behavior when no local store exists)

    All backtest paths (single_signal, sweep, portfolio) call this.
    Phase 2 book-case tests don't (they load from fixture JSON).
    """
    import os
    src = os.environ.get("BARS_SOURCE", "auto").lower()
    if src in ("local", "auto"):
        df = _load_from_local(ticker)
        if not df.empty:
            return df
        if src == "local":
            return df    # local explicit → don't fall through to DB
    return _load_from_db(ticker)


def _load_from_local(ticker: str) -> pd.DataFrame:
    """Read weekly bars from the local DuckDB (data/backtest.duckdb).
    Returns empty df if the store doesn't exist or ticker absent."""
    try:
        from app.backtest.local_store import load_bars as _local_load
    except ImportError:
        return pd.DataFrame()
    return _local_load(ticker, granularity="W")


def _load_from_db(ticker: str) -> pd.DataFrame:
    """Read weekly bars from the Supabase `bars` table (live)."""
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT bar_date, open, high, low, close, adj_close, volume "
                "FROM bars WHERE ticker = %s AND granularity = 'W' "
                "ORDER BY bar_date",
                (ticker,),
            )
            rows = cur.fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=[
        "date", "open", "high", "low", "close", "adj_close", "volume",
    ])
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "high", "low", "close", "adj_close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df.attrs["grain"] = "W"
    return df


def _signal_fired(
    result: Dict[str, Any], target_signal: str,
) -> bool:
    """True iff the analyzer's result contains the target signal_type.

    target_signal can be:
      - exact match: "action_buy", "pattern_double_bottom"
      - prefix match: "action" (matches action_buy, action_strong_buy, ...)
        Useful for "any bullish action" sweeps.
    """
    signals = extract_signals(result)
    for s in signals:
        st = s.get("signal_type", "")
        if st == target_signal or st.startswith(target_signal + "_"):
            return True
    return False


def run(
    ticker: str,
    target_signal: str,
    hold_weeks: int = 8,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Dict[str, Any]:
    """Backtest one (ticker, signal) pair.

    Walks bars chronologically. For each candidate bar with enough
    history, slices the df to that bar inclusive (PIT) and runs
    analyze_ticker(). If `target_signal` fires, records the entry +
    next-N-weeks exit.

    Returns a dict with summary stats and per-fire detail rows.
    """
    df = load_weekly_bars(ticker)
    if df.empty:
        return {"ticker": ticker, "status": "no_bars", "fires": [],
                "summary": {}}
    if len(df) < _MIN_BARS + hold_weeks:
        return {"ticker": ticker, "status": "insufficient_history",
                "rows": len(df), "fires": [], "summary": {}}

    fires: List[Dict[str, Any]] = []
    # Walk from index _MIN_BARS onwards. Each iteration:
    #   - candidate_idx i = "current Friday"
    #   - slice df[:i+1] is what's known PIT
    #   - if signal fires at i, exit at i+hold_weeks
    last_eligible_i = len(df) - hold_weeks - 1
    for i in range(_MIN_BARS, last_eligible_i + 1):
        bar_date_i = df.iloc[i]["date"].date()
        if start_date and bar_date_i < start_date:
            continue
        if end_date and bar_date_i > end_date:
            break
        # PIT slice — everything on or before this bar, nothing after.
        pit_df = df.iloc[: i + 1].copy()
        pit_df.attrs["grain"] = "W"
        try:
            result = analyze_ticker(ticker, pit_df, weekly=True, monthly=True)
        except Exception as e:
            log.debug("analyze fail at %s: %s", bar_date_i, e)
            continue
        if not _signal_fired(result, target_signal):
            continue
        entry_price = float(df.iloc[i]["close"])
        exit_idx = i + hold_weeks
        exit_price = float(df.iloc[exit_idx]["close"])
        ret = (exit_price / entry_price) - 1.0 if entry_price > 0 else 0.0
        fires.append({
            "entry_date": bar_date_i.isoformat(),
            "entry_price": entry_price,
            "exit_date": df.iloc[exit_idx]["date"].date().isoformat(),
            "exit_price": exit_price,
            "return_pct": ret * 100,
        })

    summary = _summarize(fires)
    return {
        "ticker": ticker, "signal": target_signal, "hold_weeks": hold_weeks,
        "status": "ok", "rows_scanned": last_eligible_i - _MIN_BARS + 1,
        "fires": fires, "summary": summary,
    }


def _summarize(fires: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not fires:
        return {"n": 0}
    rets = [f["return_pct"] for f in fires]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    return {
        "n": len(fires),
        "win_rate": len(wins) / len(fires),
        "avg_return_pct": statistics.mean(rets),
        "median_return_pct": statistics.median(rets),
        "best_pct": max(rets),
        "worst_pct": min(rets),
        "avg_win_pct": statistics.mean(wins) if wins else 0.0,
        "avg_loss_pct": statistics.mean(losses) if losses else 0.0,
        # 책 정신: 손실보다 이익이 충분히 커야 추세추종이 작동. payoff > 1.5
        # 면 안전. exit 룰이 추세 종료 시점 잘 잡았는지 검증.
        "payoff_ratio": (
            (statistics.mean(wins) / abs(statistics.mean(losses)))
            if wins and losses else None
        ),
    }


def _format_summary(result: Dict[str, Any]) -> str:
    """One-screen human-readable summary."""
    lines = [
        f"=== {result['ticker']} × {result.get('signal', '?')} "
        f"(hold {result.get('hold_weeks', '?')}w) ==="
    ]
    if result["status"] != "ok":
        lines.append(f"  status: {result['status']}")
        return "\n".join(lines)
    s = result["summary"]
    if s["n"] == 0:
        lines.append(f"  rows scanned: {result['rows_scanned']}")
        lines.append("  no fires")
        return "\n".join(lines)
    lines.append(f"  rows scanned: {result['rows_scanned']}")
    lines.append(f"  fires:        {s['n']}")
    lines.append(f"  win rate:     {s['win_rate']:.1%}")
    lines.append(f"  avg return:   {s['avg_return_pct']:+.2f}%")
    lines.append(f"  median:       {s['median_return_pct']:+.2f}%")
    lines.append(f"  best/worst:   {s['best_pct']:+.2f}% / {s['worst_pct']:+.2f}%")
    lines.append(f"  avg win/loss: {s['avg_win_pct']:+.2f}% / {s['avg_loss_pct']:+.2f}%")
    if s["payoff_ratio"] is not None:
        lines.append(f"  payoff ratio: {s['payoff_ratio']:.2f}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ticker", help="e.g. 005930.KS")
    p.add_argument("--signal", required=True,
                   help="signal_type (exact or prefix). e.g. action_buy, "
                        "pattern_double_bottom, action (= any bullish action).")
    p.add_argument("--hold-weeks", type=int, default=8,
                   help="exit N weeks after entry (default 8)")
    p.add_argument("--start", type=str, default=None,
                   help="ISO date — only entries on/after this")
    p.add_argument("--end", type=str, default=None,
                   help="ISO date — only entries on/before this")
    p.add_argument("--json", action="store_true",
                   help="emit JSON instead of human summary")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    sd = date.fromisoformat(args.start) if args.start else None
    ed = date.fromisoformat(args.end) if args.end else None

    result = run(args.ticker, args.signal, hold_weeks=args.hold_weeks,
                 start_date=sd, end_date=ed)

    if args.json:
        import json
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        print(_format_summary(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
