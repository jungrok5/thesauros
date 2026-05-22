"""Walk-forward analyzer driver for book-case fixtures.

Loads a fixture JSON (W + M bars frozen from FDR), feeds the weekly
df bar-by-bar into `analyze_ticker`, and collects every signal that
fires, indexed by candidate bar date.

Unlike `single_signal.run()` this harness:
  - reads from a fixture (not DB) so it works on history older than
    our 2y retention window,
  - does NOT apply a fixed hold_weeks — book cases have explicit
    book-stated exit dates, we just want to know WHEN signals fire,
  - returns the full signal-by-date map, not a return summary.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from app.book.analyzer import analyze_ticker
from app.db.scan_daily import extract_signals

log = logging.getLogger("backtest.book_cases.walk_forward")

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

_MIN_WARMUP_WEEKS = 50   # 240MA needs ~144w; signal MAs need ~50w


def load_fixture(name: str) -> Dict[str, Any]:
    """Load a fixture JSON by basename (with or without .json suffix)."""
    if not name.endswith(".json"):
        name += ".json"
    path = _FIXTURE_DIR / name
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def fixture_to_weekly_df(fixture: Dict[str, Any]) -> pd.DataFrame:
    """Extract the W bars from a fixture into the OHLCV df shape that
    analyze_ticker expects (with df.attrs["grain"] = "W")."""
    weekly = [b for b in fixture["bars"] if b["granularity"] == "W"]
    if not weekly:
        raise RuntimeError(f"fixture has no W bars: {fixture.get('ticker')}")
    df = pd.DataFrame(weekly)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    for c in ("open", "high", "low", "close", "adj_close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df.attrs["grain"] = "W"
    return df


def walk(
    fixture: Dict[str, Any],
    *,
    min_warmup: int = _MIN_WARMUP_WEEKS,
) -> Dict[date, List[Dict[str, Any]]]:
    """Walk every weekly bar from min_warmup onward; return
    {bar_date → [signal dicts]}.

    PIT-safe: at iteration i, the analyzer only sees df[: i+1].

    Slow (~150 ms / bar × ~200 bars ≈ 30s per fixture). Use
    `walk_snapshot` for tests — that loads a frozen JSON result instead
    of re-running the analyzer.
    """
    df = fixture_to_weekly_df(fixture)
    ticker = fixture["ticker"]
    out: Dict[date, List[Dict[str, Any]]] = {}
    for i in range(min_warmup, len(df)):
        pit = df.iloc[: i + 1].copy()
        pit.attrs["grain"] = "W"
        bar_dt = df.iloc[i]["date"].date()
        try:
            result = analyze_ticker(ticker, pit, weekly=True, monthly=True)
        except Exception as e:
            log.debug("analyze fail at %s: %s", bar_dt, e)
            continue
        signals = extract_signals(result)
        if signals:
            out[bar_dt] = signals
    return out


def save_walk_snapshot(
    walk_result: Dict[date, List[Dict[str, Any]]], slug: str,
) -> Path:
    """Persist a walk result as `fixtures/<slug>.walk.json` (tracked).

    The snapshot is the canonical "what our system fires" output. Tests
    compare the live walk against this snapshot, or just load it.
    Re-generate via `build_walk_snapshot.py`.
    """
    out = _FIXTURE_DIR / f"{slug}.walk.json"
    payload = {
        d.isoformat(): sigs for d, sigs in sorted(walk_result.items())
    }
    with out.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
    return out


def load_walk_snapshot(slug: str) -> Dict[date, List[Dict[str, Any]]]:
    """Inverse of save_walk_snapshot — load `<slug>.walk.json` back into
    the date-keyed dict shape walk() returns."""
    from datetime import date as _date
    path = _FIXTURE_DIR / f"{slug}.walk.json"
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    return {
        _date.fromisoformat(k): v for k, v in raw.items()
    }


def fires_near(
    walk_result: Dict[date, List[Dict[str, Any]]],
    target_date: date,
    *,
    signal_type_prefix: str,
    window_weeks: int = 6,
    timeframe: str | None = None,
) -> List[tuple[date, Dict[str, Any]]]:
    """Return every (bar_date, signal) where the signal_type starts with
    `signal_type_prefix` and bar_date is within ±window_weeks of
    target_date. If `timeframe` is given, filter by that too.

    Used by case tests as "did the system flag the book's call?"
    """
    from datetime import timedelta
    delta = timedelta(weeks=window_weeks)
    lo, hi = target_date - delta, target_date + delta
    hits: List[tuple[date, Dict[str, Any]]] = []
    for d, sigs in walk_result.items():
        if not (lo <= d <= hi):
            continue
        for s in sigs:
            st = s.get("signal_type", "")
            if not (st == signal_type_prefix
                    or st.startswith(signal_type_prefix + "_")):
                continue
            if timeframe is not None and s.get("timeframe") != timeframe:
                continue
            hits.append((d, s))
    return hits
