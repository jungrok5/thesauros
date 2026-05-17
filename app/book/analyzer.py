"""Full per-ticker analysis orchestrator.

Combines:
  - trend (월/주/일 10MA, 정배열)
  - candles (4등분선, 분류)
  - patterns (8 base + 240MA + 돌반지 + 포킹)
  - reversals (되돌림 4유형)
  - volume (11 cases + 역매집)

Output is a single Dict suitable for JSON serialization → web API → UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from app.book.trend import analyze_multi_timeframe, resample_to_period
from app.book.candles import analyze_candles, latest_candle_summary
from app.book.patterns import detect_all
from app.book.reversals import detect_all_reversals
from app.book.volume import classify_volume_case, detect_reverse_accumulation


def _signal_score(trend_signal: str, patterns: List[Dict], reversals: List[Dict],
                  volume_case: Optional[Dict]) -> float:
    """Combine all signals into a [-1, +1] book conviction score.

    Trend is the gate (no buying with monthly 10MA broken — book's hard rule).
    Then patterns and volume add directional bias.
    """
    base = {"BUY": 0.6, "HOLD": 0.0, "SELL": -0.6, "AVOID": -0.85}[trend_signal]

    # Patterns: completed bullish adds to score, completed bearish subtracts.
    for p in patterns:
        if not p["completed"]:
            continue
        delta = p["confidence"] * 0.30
        base += delta if p["direction"] == "bullish" else -delta

    for r in reversals:
        if not r.get("completed"):
            continue
        delta = r["confidence"] * 0.20
        base += delta if r["direction"] == "bullish" else -delta

    if volume_case:
        delta = volume_case["confidence"] * 0.15
        if volume_case["direction"] == "bullish":
            base += delta
        elif volume_case["direction"] == "bearish":
            base -= delta

    return max(-1.0, min(1.0, base))


def _action_from_score(trend_signal: str, score: float, patterns: List[Dict]
                       ) -> str:
    """Final action recommendation per book's hierarchy.

    Book priority: 거시 → 추세 → 패턴.
    - Monthly 10MA broken → AVOID (never override)
    - Otherwise: combine trend + pattern conviction.
    """
    if trend_signal == "AVOID":
        return "AVOID"
    if trend_signal == "SELL":
        return "SELL_OR_SHORT"
    has_completed_bullish = any(
        p["completed"] and p["direction"] == "bullish" and p["confidence"] >= 0.75
        for p in patterns
    )
    has_completed_bearish = any(
        p["completed"] and p["direction"] == "bearish" and p["confidence"] >= 0.75
        for p in patterns
    )
    if trend_signal == "BUY":
        if has_completed_bullish:
            return "STRONG_BUY"
        return "BUY"
    # HOLD
    if has_completed_bullish and score > 0.3:
        return "BUY"
    if has_completed_bearish and score < -0.3:
        return "SELL"
    return "HOLD"


def analyze_ticker(ticker: str, df: pd.DataFrame,
                   weekly: bool = True, monthly: bool = True
                   ) -> Dict:
    """Run the full book pipeline on one ticker's daily OHLCV.

    df: daily DataFrame with date, open, high, low, close, adj_close, volume.
    """
    df = df.copy()
    if "date" not in df.columns:
        df = df.reset_index().rename(columns={df.index.name or "index": "date"})
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    multi = analyze_multi_timeframe(df)
    last_candle = latest_candle_summary(df)

    # Run pattern detection on daily, weekly, monthly when sufficient history exists.
    patterns_daily = [p.to_dict() for p in detect_all(df)]
    reversals_daily = [r.to_dict() for r in detect_all_reversals(df)]

    patterns_weekly = []
    if weekly:
        wdf = resample_to_period(df, "W").reset_index().rename(columns={"index": "date"})
        if "date" not in wdf.columns:
            wdf = wdf.rename(columns={wdf.columns[0]: "date"})
        patterns_weekly = [p.to_dict() for p in detect_all(wdf)]

    patterns_monthly = []
    if monthly:
        mdf = resample_to_period(df, "M").reset_index().rename(columns={"index": "date"})
        if "date" not in mdf.columns:
            mdf = mdf.rename(columns={mdf.columns[0]: "date"})
        patterns_monthly = [p.to_dict() for p in detect_all(mdf)]

    volume_case = classify_volume_case(df)
    reverse_accum = detect_reverse_accumulation(df)

    # Combine patterns from all timeframes for scoring, but tag timeframe.
    all_patterns: List[Dict] = []
    for p in patterns_daily:
        all_patterns.append({**p, "timeframe": "daily"})
    for p in patterns_weekly:
        all_patterns.append({**p, "timeframe": "weekly"})
    for p in patterns_monthly:
        all_patterns.append({**p, "timeframe": "monthly"})

    # Sort by (timeframe weight, confidence)
    tf_weight = {"monthly": 3, "weekly": 2, "daily": 1}
    all_patterns.sort(key=lambda p: (-tf_weight.get(p.get("timeframe"), 0),
                                     -p["confidence"]))

    vc_dict = volume_case.to_dict() if volume_case else None
    score = _signal_score(
        multi.book_signal, all_patterns, reversals_daily, vc_dict
    )
    action = _action_from_score(multi.book_signal, score, all_patterns)

    # Build entry/stop/target from top completed bullish pattern (if any)
    entry_block = None
    if action in ("BUY", "STRONG_BUY"):
        for p in all_patterns:
            if p["completed"] and p["direction"] == "bullish":
                entry_block = {
                    "entry": p["entry"],
                    "stop": p["stop"],
                    "target": p["target"],
                    "based_on": f"{p['kind']} ({p.get('timeframe', 'daily')})",
                }
                break
        # Fallback: 10MA-based stop
        if entry_block is None and multi.daily and multi.daily.ma_10:
            last_close = float(df["close"].iloc[-1])
            entry_block = {
                "entry": last_close,
                "stop": multi.daily.ma_10 * 0.97,
                "target": None,
                "based_on": "일봉 10MA 스톱",
            }
    elif action in ("SELL_OR_SHORT", "SELL"):
        last_close = float(df["close"].iloc[-1])
        # use weekly/monthly 10MA as exit reference
        ma10 = (multi.monthly.ma_10 if multi.monthly else None) or \
               (multi.weekly.ma_10 if multi.weekly else None) or \
               (multi.daily.ma_10 if multi.daily else last_close)
        entry_block = {
            "entry": last_close,
            "stop": last_close * 1.05,    # inverse stop above current price
            "target": None,
            "based_on": "월/주봉 10MA 이탈 → 청산 또는 인버스 진입",
        }

    return {
        "ticker": ticker,
        "as_of": str(df["date"].iloc[-1].date()),
        "last_close": round(float(df["close"].iloc[-1]), 4),
        "rows": len(df),
        "action": action,
        "book_score": round(score, 3),
        "trend": multi.to_dict(),
        "last_candle": last_candle,
        "patterns": all_patterns,
        "reversals": reversals_daily,
        "volume_case": vc_dict,
        "reverse_accumulation": reverse_accum,
        "entry_plan": entry_block,
    }


def load_ticker_data(ticker: str, years: int = 5) -> Optional[pd.DataFrame]:
    """Load OHLCV for the requested ticker.

    Source order:
      1. Supabase bars_daily (canonical, populated by cron)
      2. yfinance live fetch (only when Supabase has nothing — useful for
         brand-new tickers in dev)

    DuckDB is no longer consulted — all bars are migrated to Supabase
    (see migrations/007 + app.db.migrate_duckdb_to_supabase).
    """
    from datetime import date, timedelta
    from app.db import get_conn

    # 1) Supabase bars_daily
    try:
        with get_conn(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT bar_date, open, high, low, close, adj_close, volume "
                    "FROM bars_daily WHERE ticker = %s ORDER BY bar_date",
                    (ticker,),
                )
                rows = cur.fetchall()
        if rows:
            df = pd.DataFrame(rows, columns=[
                "date", "open", "high", "low", "close", "adj_close", "volume",
            ])
            df["date"] = pd.to_datetime(df["date"])
            for col in ("open", "high", "low", "close", "adj_close", "volume"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
            return df
    except Exception:
        # Supabase unreachable in dev — fall through to live fetch.
        pass

    # 2) Live fallback (yfinance)
    import yfinance as yf
    start = (date.today() - timedelta(days=years * 365 + 30)).isoformat()
    try:
        t = yf.Ticker(ticker)
        live = t.history(start=start, auto_adjust=False, actions=False)
    except Exception:
        return None
    if live is None or live.empty:
        return None
    live = live.reset_index().rename(columns={
        "Date": "date", "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Adj Close": "adj_close", "Volume": "volume",
    })
    live["date"] = pd.to_datetime(live["date"]).dt.tz_localize(None)
    return live
