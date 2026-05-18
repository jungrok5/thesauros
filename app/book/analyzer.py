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
    """Run the full book pipeline on one ticker's OHLCV.

    df: DataFrame with date, open, high, low, close, adj_close, volume.
    Input grain is taken from df.attrs["grain"] — "D" (default, daily input)
    or "W" (weekly input, used for US tickers via Naver since yfinance is
    blocked on cloud runners). When grain="W" we have no daily history;
    daily-timeframe pattern detection and daily MAs are skipped.
    """
    df = df.copy()
    if "date" not in df.columns:
        df = df.reset_index().rename(columns={df.index.name or "index": "date"})
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    grain = df.attrs.get("grain", "D")

    multi = analyze_multi_timeframe(df, input_grain=grain)
    last_candle = latest_candle_summary(df)

    # Pattern detection per timeframe.
    if grain == "W":
        # Input is weekly — no daily history available.
        patterns_daily: List[Dict] = []
        reversals_daily: List[Dict] = []
        # Weekly patterns run on the input df directly.
        patterns_weekly = [p.to_dict() for p in detect_all(df)] if weekly else []
        patterns_monthly = []
        if monthly:
            mdf = resample_to_period(df, "M").reset_index().rename(columns={"index": "date"})
            if "date" not in mdf.columns:
                mdf = mdf.rename(columns={mdf.columns[0]: "date"})
            patterns_monthly = [p.to_dict() for p in detect_all(mdf)]
    else:
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

    # volume_case + reverse_accum are computed on whatever grain we have.
    # They both look at recent N bars relative to history — semantics shift
    # slightly under weekly input but the comparative logic still makes sense.
    volume_case = classify_volume_case(df)
    reverse_accum = detect_reverse_accumulation(df) if grain != "W" else None

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

    # Build entry/stop/target from top completed bullish pattern (if any).
    # Skip stale patterns (detected_at more than ~2 months ago) so we
    # don't surface trade plans from a breakout that already played out.
    # Skip patterns that fail entry < target sanity for bullish plans —
    # historically the H&S detectors could mis-orient the projection.
    entry_block = None
    if action in ("BUY", "STRONG_BUY"):
        from datetime import datetime, timedelta
        as_of_ts = pd.to_datetime(df["date"].iloc[-1])
        STALE_DAYS = 60
        last_close = float(df["close"].iloc[-1])
        for p in all_patterns:
            if not (p["completed"] and p["direction"] == "bullish"):
                continue
            # Sanity: bullish plan must have entry < target and stop < entry.
            entry_v = p.get("entry")
            target_v = p.get("target")
            stop_v = p.get("stop")
            if entry_v is None or target_v is None or stop_v is None:
                continue
            if not (stop_v < entry_v < target_v):
                continue
            # Freshness: skip if the pattern completed too long ago — the
            # breakout has already happened and the plan would be stale.
            det = p.get("detected_at")
            if det:
                try:
                    det_ts = pd.to_datetime(det)
                    if (as_of_ts - det_ts) > timedelta(days=STALE_DAYS):
                        continue
                except Exception:
                    pass
            # Don't enter at a stale entry far below current price either.
            if entry_v < last_close * 0.7:
                continue
            # Tighten the stop with a trailing 주봉 10MA when the pattern's
            # traditional stop (pattern bottom) is too far below current
            # price to be practical. Book's rule "10MA 이탈 = 청산" gives
            # the natural trailing stop once a breakout has run.
            tight_stop = None
            if multi.weekly and multi.weekly.ma_10:
                tight_stop = multi.weekly.ma_10 * 0.97
            elif multi.monthly and multi.monthly.ma_10:
                tight_stop = multi.monthly.ma_10 * 0.97
            effective_stop = max(stop_v, tight_stop) if tight_stop else stop_v
            entry_block = {
                "entry": entry_v,
                "stop": effective_stop,
                "target": target_v,
                "based_on": (
                    f"{p['kind']} ({p.get('timeframe', 'daily')})"
                    + ("  · 손절은 주봉 10MA" if effective_stop != stop_v else "")
                ),
            }
            break
        # Fallback: 10MA-based stop. Prefer daily; under weekly input
        # (US via Naver) fall back to weekly MA.
        if entry_block is None:
            last_close = float(df["close"].iloc[-1])
            ma10 = (multi.daily.ma_10 if multi.daily else None) or \
                   (multi.weekly.ma_10 if multi.weekly else None)
            if ma10:
                entry_block = {
                    "entry": last_close,
                    "stop": ma10 * 0.97,
                    "target": None,
                    "based_on": "일봉 10MA 스톱" if multi.daily else "주봉 10MA 스톱",
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
    """Load weekly OHLCV for the requested ticker.

    Source order:
      1. Supabase `bars` granularity='W' (canonical, populated by cron
         which resamples KR FDR daily → W+M and fetches Naver weekly
         direct for US).
      2. Naver weekCandle live fetch — fallback for brand-new US tickers
         the cron hasn't ingested yet (e.g. just-added watchlist names
         analyzed via the workflow_dispatch path).

    Returned df.attrs["grain"]: always "W" — the analyzer's daily code
    paths are inactive for the weekly-pivot architecture.
    """
    from app.db import get_conn

    # 1) Supabase bars (weekly)
    try:
        with get_conn(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT bar_date, open, high, low, close, adj_close, volume "
                    "FROM bars WHERE ticker = %s AND granularity = 'W' "
                    "ORDER BY bar_date",
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
            df.attrs["grain"] = "W"
            return df
    except Exception:
        # Supabase unreachable in dev — fall through to live Naver.
        pass

    # 2) Live Naver weekly — only meaningful for non-KR tickers (KR is
    #    fully populated by the FDR cron). For US watchlist adds before
    #    the next cron pass this gives ~2y weekly bars instantly.
    if not _looks_kr(ticker):
        try:
            from app.data.naver_bars import fetch_weekly
        except Exception:
            return None
        wdf = fetch_weekly(ticker, years=years)
        if wdf is not None and not wdf.empty:
            return wdf

    return None


def _looks_kr(ticker: str) -> bool:
    """KR tickers in our master are always suffixed .KS or .KQ."""
    t = ticker.upper()
    return t.endswith(".KS") or t.endswith(".KQ")
