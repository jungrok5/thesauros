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
from app.book.indicators import compute_indicators


def pattern_sort_key(p: Dict) -> tuple:
    """Sort key for entry_plan candidate selection. 2026-05-26 audit
    reform:

    1. **weekly-first** — book ch.4: 매매 = 주봉 종가. Monthly is for
       confirming the bigger trend (240MA), not entry timing.
       Previous (monthly:3, weekly:2) sat the strong weekly 삼중바닥
       conf=0.87 behind a weak monthly conf=0.56 in the 383800.KS case.
    2. **fake_volume penalty** — detector flags `extra.fake_volume`
       when volume isn't monotonically rising during pattern formation
       (책 p254/p276 페이크 캔들 의심). -0.3 to confidence in sort,
       enough to put a clean 0.6 above a fake 0.85 while keeping
       very-strong clean signals (≥0.9) in the lead.
    """
    tf_rank = {"weekly": 0, "monthly": 1, "daily": 2}.get(
        p.get("timeframe"), 3
    )
    fake = (p.get("extra") or {}).get("fake_volume", False)
    eff_conf = float(p.get("confidence") or 0) - (0.3 if fake else 0)
    return (tf_rank, -eff_conf)


def _signal_score(trend_signal: str, patterns: List[Dict], reversals: List[Dict],
                  volume_case: Optional[Dict]) -> float:
    """Combine all signals into a [-1, +1] book conviction score.

    Trend is the gate (no buying with monthly 10MA broken — book's hard rule).
    Then patterns and volume add directional bias.
    """
    base = {"BUY": 0.6, "HOLD": 0.0, "SELL": -0.6, "AVOID": -0.85}[trend_signal]

    # Patterns: completed bullish adds to score, completed bearish subtracts.
    # Invalidated patterns are EXCLUDED — book룰: 쌍바닥의 전저점이 깨지면
    # 첫 매수세 + 실망 매물로 패턴 자체가 무효 (p254-255). Once a pattern
    # fails its precondition it stops being a signal.
    for p in patterns:
        if not p["completed"]:
            continue
        if p.get("invalidated"):
            continue
        # fake_volume penalty (2026-05-26): detector marks the pattern's
        # extra dict when volume isn't monotonically rising. Book p254/
        # p276 calls this a 페이크 캔들 의심 — confidence should reflect
        # it. score cap is still 1.0 so the effect is mostly visible
        # when a fake pattern is the lone bullish signal.
        conf = float(p.get("confidence") or 0)
        if (p.get("extra") or {}).get("fake_volume"):
            conf *= 0.5
        delta = conf * 0.30
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


def _mark_invalidated_patterns(patterns: List[Dict], last_close: float) -> None:
    """Walk completed patterns and stamp `invalidated=True` when price
    has moved past the book's invalidation level.

    Book룰 (p254-273):
      - 쌍바닥 / 삼중바닥 / Cup w. Handle: close < 마지막 바닥 = 무효
        (책: "전저점 지키기" 전제 조건 위반)
      - All bullish patterns w/ neckline/rim/ma_value in extras:
        close below that level = breakout failed → invalidated
      - 쌍봉 / H&S / 삼고점: close > 마지막 peak (or neckline from above)
        = "N자 탈출" → 무효
    Mutates each pattern dict in place. Idempotent.
    """
    for p in patterns:
        if not p.get("completed"):
            continue
        if p.get("invalidated"):
            continue
        direction = p.get("direction")
        kind = p.get("kind") or ""
        extra = p.get("extra") or {}

        # Bullish: close below a defining floor invalidates.
        if direction == "bullish":
            # 1) Pattern-bottom: 쌍바닥/삼중바닥 etc.
            bottoms = extra.get("bottoms")
            if isinstance(bottoms, list) and bottoms:
                try:
                    last_bottom = min(
                        float(b["price"]) for b in bottoms
                        if isinstance(b, dict) and "price" in b
                    )
                    if last_close < last_bottom * 0.99:
                        p["invalidated"] = True
                        p["invalidation_reason"] = (
                            f"close {last_close:.4g} < 마지막 바닥 "
                            f"{last_bottom:.4g} (전저점 깨짐, 책 p254 무효)"
                        )
                        continue
                except Exception:
                    pass
            # 2) Breakout-level: neckline / rim / ma_240 / ma_value
            for key in ("neckline", "rim", "ma_240", "ma_value"):
                lvl = extra.get(key)
                if isinstance(lvl, (int, float)) and lvl > 0:
                    if last_close < float(lvl) * 0.97:
                        p["invalidated"] = True
                        p["invalidation_reason"] = (
                            f"close {last_close:.4g} < {key} "
                            f"{float(lvl):.4g} (돌파선 재이탈)"
                        )
                        break
            if p.get("invalidated"):
                continue

        # Bearish: close above the defining ceiling invalidates ("N자 탈출").
        if direction == "bearish":
            peaks = extra.get("peaks") or extra.get("tops")
            if isinstance(peaks, list) and peaks:
                try:
                    last_peak = max(
                        float(b["price"]) for b in peaks
                        if isinstance(b, dict) and "price" in b
                    )
                    if last_close > last_peak * 1.01:
                        p["invalidated"] = True
                        p["invalidation_reason"] = (
                            f"close {last_close:.4g} > 마지막 봉우리 "
                            f"{last_peak:.4g} (N자 탈출, 책 p260)"
                        )
                        continue
                except Exception:
                    pass


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
        p["completed"] and p["direction"] == "bullish"
        and p["confidence"] >= 0.75
        and not p.get("invalidated")
        for p in patterns
    )
    has_completed_bearish = any(
        p["completed"] and p["direction"] == "bearish"
        and p["confidence"] >= 0.75
        and not p.get("invalidated")
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
    # Perf caches (find_swings, resample) are keyed by id(df). After a
    # previous call's intermediate DataFrames are GC'd, those id values
    # become reusable — a new pit_df might collide with stale entries.
    # Clear both caches at the start of every analyze to scope them to
    # a single call (≈ 100 cache hits / call, GC'd at call end).
    from app.book._swings import clear_swings_cache
    from app.book.trend import clear_resample_cache
    clear_swings_cache()
    clear_resample_cache()

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

    # Sort: weekly-first + fake_volume penalty. See pattern_sort_key
    # docstring for the 2026-05-26 audit context.
    all_patterns.sort(key=pattern_sort_key)

    vc_dict = volume_case.to_dict() if volume_case else None

    # Stamp invalidation on completed patterns whose precondition the
    # current price has broken (LG우 case: 쌍바닥 neckline 81,000 but
    # close 72,200 → pattern was actively kept "completed" in the score
    # despite having clearly failed). _signal_score now ignores
    # invalidated patterns.
    _mark_invalidated_patterns(all_patterns, float(df["close"].iloc[-1]))

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

    # 장대음봉 (저승사자) gate — Book Ch.2 p262, 264.
    # A big bearish bar (already tagged by classify_candle when body ≥
    # 2× body_avg_20) is the book's explicit sell signal. It signals
    # forced distribution: a market that just refused to follow through
    # on bullish moves. The exact "저승사자" sub-case the book teaches
    # is "장대음봉 + 10MA 하향 이탈 = 청산" — when the same bar takes
    # close below the weekly 10MA, downgrade aggressively to SELL_OR_SHORT.
    # Otherwise (장대음봉 but still above 10MA), downgrade to HOLD so
    # we don't actively recommend buying into a market that just dumped.
    if last_candle is not None:
        tags = last_candle.get("tags") or []
        if "장대음봉" in tags:
            ma10w = (
                float(multi.weekly.ma_10)
                if multi.weekly and multi.weekly.ma_10
                else None
            )
            if action in ("BUY", "STRONG_BUY"):
                reason = "마지막 봉 장대음봉 — 책 룰: 매도 압력"
                if ma10w and last_close < ma10w:
                    action = "SELL_OR_SHORT"
                    reason = "저승사자 캔들 (장대음봉 + 주봉 10MA 하향 이탈)"
                else:
                    action = "HOLD"
                stretch_reason = (
                    f"{stretch_reason} · {reason}" if stretch_reason else reason
                )

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
        # 2026-05-26 — two-pass: prefer non-fake patterns. Some tickers
        # have fake_volume on EVERY bullish pattern (e.g., 069730.KS
        # weekly 삼중바닥 conf=0.56 fake — the only completed bullish
        # weekly pattern). In that case the second pass accepts fake
        # rather than no entry_plan at all; the BookVerdict still
        # surfaces the fake-volume warning chip so the user sees it.
        passes = (False, True)   # first pass = clean only, then allow fake
        for allow_fake in passes:
            if entry_block is not None:
                break
            for p in all_patterns:
                if not (p["completed"] and p["direction"] == "bullish"):
                    continue
                if p.get("invalidated"):
                    continue
                if not allow_fake and (p.get("extra") or {}).get("fake_volume"):
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

    # Multi-bar candle context tags (book p249-250) — checked on the
    # last 1-3 bars and appended to last_candle["tags"]. These don't
    # change the action gate but enrich the BookVerdict narrative.
    try:
        if last_candle is not None and len(df) >= 3:
            tags_extra: List[str] = []
            # 주고받고: prior bar 장대양봉, current small bearish bar
            # whose close sits in the prior 75 % safe zone.
            prev = df.iloc[-2]
            curr = df.iloc[-1]
            prev_body = abs(float(prev["close"]) - float(prev["open"]))
            curr_body = abs(float(curr["close"]) - float(curr["open"]))
            if (
                float(prev["close"]) > float(prev["open"])     # prev bull
                and prev_body > 0
                and float(curr["close"]) < float(curr["open"]) # curr bear
                and curr_body / max(prev_body, 1e-9) < 0.4     # small body
                and float(curr["close"]) >= float(prev["open"])
                  + 0.75 * (float(prev["close"]) - float(prev["open"]))
            ):
                tags_extra.append("주고받고")
            # 은둔형 장대양봉: 3-bar cumulative gain ≥ 5 %, each bar
            # small bullish body.
            if len(df) >= 3:
                three = df.tail(3)
                bars_bullish = all(
                    float(r["close"]) > float(r["open"]) for _, r in three.iterrows()
                )
                cum_gain = (
                    float(three["close"].iloc[-1]) / float(three["open"].iloc[0]) - 1
                    if float(three["open"].iloc[0]) > 0 else 0
                )
                bodies_small = all(
                    abs(float(r["close"]) - float(r["open"])) / max(float(r["open"]), 1e-9) < 0.03
                    for _, r in three.iterrows()
                )
                if bars_bullish and bodies_small and cum_gain >= 0.05:
                    tags_extra.append("은둔형장대양봉")
            for t in tags_extra:
                if t not in (last_candle.get("tags") or []):
                    last_candle.setdefault("tags", []).append(t)
    except Exception:
        pass

    # 4등분선 안전지대 판정 (book p218-223). Find the most recent
    # 장대양봉 catalyst pattern, anchor the quarter zones on its body,
    # then report where current_price sits.
    quarter_zone_state: Optional[str] = None
    quarter_anchor: Optional[Dict[str, Any]] = None
    try:
        from app.book.candles import quarter_zone as _qz
        for p in all_patterns:
            if not isinstance(p, dict):
                continue
            if "catalyst" not in (p.get("kind") or ""):
                continue
            ex = p.get("extra") or {}
            cat_open = ex.get("catalyst_open")
            cat_close = ex.get("catalyst_close")
            if (
                isinstance(cat_open, (int, float))
                and isinstance(cat_close, (int, float))
                and cat_close > cat_open > 0
            ):
                quarter_zone_state = _qz(
                    float(cat_open), float(cat_close), last_close,
                )
                quarter_anchor = {
                    "open": float(cat_open),
                    "close": float(cat_close),
                    "q25": ex.get("q25"),
                    "q50": ex.get("q50"),
                    "q75": ex.get("q75"),
                }
                break
    except Exception:
        quarter_zone_state = None

    # RSI / MACD (책 정신상 second-class corroboration — 가격/캔들/거래량
    # 다음 우선순위). weekly bars 위에서 계산, trend label과 함께
    # narrative emit. 110주 미만이면 indicators_snapshot = None.
    indicators_dict: Optional[Dict[str, Any]] = None
    try:
        weekly_label = multi.weekly.label if multi.weekly else None
        snap = compute_indicators(df, trend_label=weekly_label)
        if snap is not None:
            indicators_dict = snap.to_dict()
    except Exception:
        indicators_dict = None

    # as_of = the weekly bar's date (Friday week-ending in Naver's
    # convention). NB this is NOT the actual last trading day the
    # close represents — for an in-progress week on a Tuesday, the
    # close is Tuesday's but bar_date is the upcoming Friday. The
    # /stocks/[ticker] page hides this field in the header and
    # surfaces the authoritative date via <LastClose/> (live Naver/
    # Yahoo). Downstream callers that still consume `as_of` (scan
    # writer, telegram alerts) treat it as the week-key, which is
    # correct.
    result: Dict[str, Any] = {
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
        "quarter_zone": quarter_zone_state,
        "quarter_anchor": quarter_anchor,
        "indicators": indicators_dict,
    }
    # Buy-eligibility verdict — single source of truth shared by the
    # page's NoviceVerdict card AND the telegram alert worker. Computed
    # AFTER all the gate inputs are populated so it can read them. See
    # `app/book/eligibility.py` for the rule + the TS parity gate.
    from app.book.eligibility import compute_eligibility
    result["eligibility"] = compute_eligibility(result)
    return result


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

    # Live Naver fallback removed 2026-05-22 — US universe deactivated
    # via migration 045 (책 정신 + Naver/yfinance cloud-IP 차단).
    # Non-KR tickers return None; the UI shows a "분석 중단" notice and
    # offers chart-image analysis (P_VISION) as the replacement.
    return None


def _looks_kr(ticker: str) -> bool:
    """KR tickers in our master are always suffixed .KS or .KQ."""
    t = ticker.upper()
    return t.endswith(".KS") or t.endswith(".KQ")
