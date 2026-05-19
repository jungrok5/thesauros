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

    # Pre-compute stretch metrics so the post-rally guard can downgrade
    # action BEFORE entry_plan is built. Three signals book treats as
    # "추세는 살았지만 자리 한참 지남":
    #   - 8-bar trailing return ≥ 50 %         → 책 "+50 % 룰" 직접 위반
    #   - last_close / ma_240 − 1 > 1.0 (+100%)→ 240MA 한참 위 (RKLB +250 %)
    #   - 52-w position ≥ 0.85 AND rally ≥ 0.30→ 52w 최고가 근처 + 단기 급등
    # If any fires while action is BUY/STRONG_BUY, downgrade to HOLD so
    # the entry_plan branch below never offers a chase entry. We record
    # the gate that fired in `stretch_reason` for UI surfacing.
    last_close = float(df["close"].iloc[-1])
    try:
        tail52_pre = df.tail(52)
        # Defensive: FDR / Naver occasionally return OHLV=0 placeholder
        # rows for non-trading / suspended days. The ingestor now drops
        # them at source, but historical poisoning persists until the
        # 504-ticker backfill clears. Exclude any bar with high=0 OR
        # low=0 from the window so we never normalise against a 0 floor
        # (the 009310.KS bug — 52w pos came out at 311 % because
        # tail52_low.min() landed on a corrupt 0 row).
        valid = tail52_pre[
            (tail52_pre["high"] > 0) & (tail52_pre["low"] > 0)
        ]
        if len(valid) < 4:
            pos_52w_pre = None
        else:
            _hi52 = float(valid["high"].max())
            _lo52 = float(valid["low"].min())
            pos_52w_pre = (
                float((last_close - _lo52) / (_hi52 - _lo52))
                if _hi52 > _lo52 else 0.5
            )
    except Exception:
        pos_52w_pre = None
    try:
        _rw = min(8, len(df) - 1)
        _start = float(df["close"].iloc[-_rw - 1])
        rally_pre = float((last_close / _start) - 1) if _start > 0 else 0.0
    except Exception:
        rally_pre = None
    ma_240 = None
    if multi.weekly and multi.weekly.ma_240:
        ma_240 = float(multi.weekly.ma_240)
    elif multi.monthly and multi.monthly.ma_240:
        ma_240 = float(multi.monthly.ma_240)
    ma240_dist = (
        (last_close / ma_240) - 1.0 if ma_240 and ma_240 > 0 else None
    )

    stretch_reason: Optional[str] = None
    if action in ("BUY", "STRONG_BUY"):
        reasons = []
        if rally_pre is not None and rally_pre >= 0.50:
            reasons.append(f"8주 +{rally_pre * 100:.0f}% (책 +50% 룰 위반)")
        if ma240_dist is not None and ma240_dist > 1.0:
            reasons.append(f"240MA 대비 +{ma240_dist * 100:.0f}%")
        if (
            pos_52w_pre is not None
            and pos_52w_pre >= 0.85
            and rally_pre is not None
            and rally_pre >= 0.30
        ):
            reasons.append(
                f"52w 위치 {pos_52w_pre * 100:.0f}% + 8주 +{rally_pre * 100:.0f}%"
            )
        if reasons:
            stretch_reason = " · ".join(reasons)
            action = "HOLD"

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
            # FINAL sanity — the trailing-stop tightening above could in
            # principle push effective_stop above target_v (for a pattern
            # whose target is very close to current price). Drop instead
            # of surfacing a stop > target plan to the user.
            if not (effective_stop < entry_v < target_v):
                continue
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

    # Final entry_plan sanity gate — fail-loud rather than fail-confusing.
    # The picker logic above already checks invariants, but if anyone
    # changes downstream code (or rebuilds entry_block via a different
    # branch), this catches it before users see a target-below-entry
    # plan like the 국보디자인 2026-05-22 bug.
    if entry_block is not None:
        e = entry_block.get("entry")
        s = entry_block.get("stop")
        t = entry_block.get("target")
        if e is not None and s is not None:
            if action in ("BUY", "STRONG_BUY"):
                ok = s < e and (t is None or e <= t)
            else:
                # SELL plan: stop above entry, target (if any) below
                ok = e <= s and (t is None or t <= e)
            if not ok:
                # Drop the malformed plan instead of surfacing it.
                entry_block = None

    # Stop-distance sanity for BUY plans. Book룰: 손절 폭은 진입가
    # 대비 8~10 % 내. 폭이 -15 % 를 넘어가면 추세 후반부에서 10MA가
    # 진입가에서 한참 멀어진 케이스(RKLB +250 % 위에서 stop 주봉 10MA
    # = -37 %)다. 진입가-stop 거리만으로도 책 정신상 신규 매수 자격 X.
    if (
        entry_block is not None
        and action in ("BUY", "STRONG_BUY")
    ):
        e = entry_block.get("entry")
        s = entry_block.get("stop")
        if e is not None and s is not None and e > 0:
            stop_dist = (e - s) / e
            if stop_dist > 0.15:
                entry_block = None
                # The action is no longer actionable as a fresh entry;
                # downgrade so the verdict / UI reflects "보유는 OK,
                # 신규는 X" rather than "BUY without plan".
                if action in ("BUY", "STRONG_BUY"):
                    action = "HOLD"
                    if stretch_reason is None:
                        stretch_reason = (
                            f"손절 폭 {stop_dist * 100:.0f}% (책 룰 -10% 초과)"
                        )
                    else:
                        stretch_reason += (
                            f" · 손절 폭 {stop_dist * 100:.0f}%"
                        )

    # Consolidation / 박스권 헤드라인 signal — used by the BookVerdict
    # 매복 detector. We pre-compute it here so the page doesn't need to
    # re-fetch bars: the (max-min)/last_close of the most recent N bars.
    # When this is tight (≤ 6 %) over the last 4 bars, the chart is in
    # a "기간 조정" box regardless of whether the strict MA-convergence
    # pattern fires (its 60-MA spread check is too tight for some box
    # cases like 국보디자인 2026-05-22).
    try:
        recent4 = df["close"].iloc[-4:].astype(float)
        last_close = float(df["close"].iloc[-1])
        if last_close > 0 and len(recent4) >= 4:
            cons_ratio = float((recent4.max() - recent4.min()) / last_close)
        else:
            cons_ratio = None
    except Exception:
        cons_ratio = None

    # 52-week position + 8-week rally were computed earlier (pre-action)
    # so the stretch guard could consume them; we just re-surface them in
    # the result for the page / BookVerdict.
    pos_52 = pos_52w_pre
    rally_pct = rally_pre

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
        "consolidation_ratio": cons_ratio,
        "position_in_52w": pos_52,
        "rally_8w_pct": rally_pct,
        "stretch_reason": stretch_reason,
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
