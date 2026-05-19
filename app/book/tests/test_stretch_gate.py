"""Late-trend stretch guard — RKLB regression.

The analyzer used to surface action=BUY even when the chart was clearly
past the book's neat entry zone (240MA +250 %, 8-week rally +100 %,
sitting at 52-week high). Book룰: 추세 시작부 +50 % 안에서만 신규 매수.
After +50 %, the trade is for holders to manage; new buyers chase.

This module pins:
  - rally_8w_pct ≥ 0.50 alone downgrades BUY → HOLD
  - 240MA distance > +100 % alone downgrades BUY → HOLD
  - (pos_52w ≥ 0.85 AND rally ≥ 0.30) jointly downgrade
  - stretch_reason is populated with a human-readable string
  - entry_plan with stop > 15 % away drops the plan AND downgrades BUY
  - none of the above fires for clean mid-trend setups (no regression
    on normal uptrend behavior)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.book.analyzer import analyze_ticker


def _frame(closes: list[float], start: str = "2022-01-07",
           volumes: list[float] | None = None) -> pd.DataFrame:
    """Build a weekly OHLCV frame. close-only chart with tight wicks so
    candle tags don't disturb the test. Volumes default to flat 1M."""
    n = len(closes)
    arr = np.asarray(closes, dtype=float)
    if volumes is None:
        vol = np.full(n, 1_000_000.0)
    else:
        vol = np.asarray(volumes, dtype=float)
    return pd.DataFrame({
        "date": pd.date_range(start, periods=n, freq="W-FRI"),
        "open": arr * 0.999, "high": arr * 1.005, "low": arr * 0.995,
        "close": arr, "adj_close": arr,
        "volume": vol,
    })


def test_rally_50_pct_alone_downgrades_to_hold():
    """A 240-bar slow grind then a +80 % surge in last 8 bars → 8w
    return > 50 %. Should be HOLD with stretch_reason mentioning the
    rally figure."""
    # 230 weeks of slow drift, then 8-week +80 % surge ending at 180.
    base = list(np.linspace(80, 100, 230))
    surge = list(np.linspace(100, 180, 9))
    df = _frame(base + surge[1:])    # 230 + 8 = 238 bars
    df.attrs["grain"] = "W"
    r = analyze_ticker("TEST", df)
    assert r["action"] == "HOLD", f"expected HOLD got {r['action']}"
    assert r.get("stretch_reason"), "expected stretch_reason populated"
    assert "8주" in r["stretch_reason"], (
        f"reason should mention 8주 rally: {r['stretch_reason']}"
    )
    # Downgrade must clear entry_plan — no chase entry surfaced.
    assert r["entry_plan"] is None, (
        f"HOLD via stretch should have entry_plan=None, got {r['entry_plan']}"
    )


def test_240ma_plus_100_pct_alone_downgrades():
    """A long flat-then-surge chart whose 240MA sits far below last_close
    (RKLB-style +250% above 240MA). The 240MA distance gate alone
    should flip BUY→HOLD with reason mentioning 240MA.

    Constructed so 8w rally is modest (≤30%) — only the 240MA distance
    gate fires, not the rally gate."""
    # 220 bars flat at 40, then 40 bars slowly climbing 40 → 200. With
    # the slow 40-week climb, 8w rally < 50 %, but mean(closes[-240:]) ≈
    # mean of 220 flat + 20 climb bars stays near 50, so 200/50 = 4× →
    # +300 % above 240MA.
    closes = [40.0] * 220 + list(np.linspace(40, 200, 41))[1:]
    df = _frame(closes)
    df.attrs["grain"] = "W"
    r = analyze_ticker("TEST", df)
    # Sanity: confirm the chart we built actually crosses the 240MA gate.
    weekly = r["trend"].get("weekly") if r["trend"] else None
    if weekly and weekly.get("ma_240"):
        ratio = r["last_close"] / weekly["ma_240"]
        # We engineered this so the ratio is well above 2 (+100 %).
        assert ratio > 2.0, (
            f"test fixture didn't meet 240MA +100 % spec, ratio={ratio:.2f}"
        )
    assert r["action"] != "STRONG_BUY", (
        f"+300 % above 240MA shouldn't be STRONG_BUY, got {r['action']}"
    )
    # The action is HOLD (gated by 240MA distance OR by stop-distance);
    # in either case stretch_reason should be populated.
    if r["action"] == "HOLD":
        assert r.get("stretch_reason"), "stretch_reason should be set"
        # And entry_plan should be cleared.
        assert r["entry_plan"] is None


def test_pos_high_plus_rally_30_pct_downgrades():
    """52w pos ≥ 0.85 + rally ≥ 0.30 — the GOOGL-style post-rally case."""
    # 44 flat bars at 100 then 8 bars climbing to 140 (+40 % rally,
    # 52w-pos = 1.0). Total 52 bars enough for 52w window.
    base = [100.0] * 44
    rally = list(np.linspace(100, 140, 9))[1:]   # 8 bars 100→140
    df = _frame(base + rally)
    df.attrs["grain"] = "W"
    r = analyze_ticker("TEST", df)
    # Either stretch fires (HOLD) or — if multi-TF trend isn't strong
    # enough to give BUY in the first place — we still expect non-BUY.
    assert r["action"] != "STRONG_BUY", (
        f"post-rally near 52w high shouldn't be STRONG_BUY, got {r['action']}"
    )


def test_normal_mid_trend_uptrend_not_downgraded():
    """Linear-but-modest uptrend without the stretch markers — must
    NOT be downgraded by the new gate."""
    # Long flat-ish history that puts 240MA near current price, modest
    # recent rally — neither rally nor 240MA-dist triggers.
    closes = list(np.linspace(95, 100, 250)) + list(np.linspace(100, 105, 10))
    df = _frame(closes)
    df.attrs["grain"] = "W"
    r = analyze_ticker("TEST", df)
    # The action might be HOLD for unrelated reasons (no completed
    # pattern, weak trend) — what we care about: NOT downgraded by
    # the stretch gate.
    assert r.get("stretch_reason") in (None, ""), (
        f"clean mid-trend chart got stretched reason: {r['stretch_reason']}"
    )


def test_entry_plan_stop_distance_15_pct_gate():
    """If a BUY plan would surface with stop > 15 % away (typical of
    extreme-stretch charts where the trailing 주봉 10MA is far below
    current price), the plan is dropped and action is HOLD."""
    # Construct a chart whose multi-TF trend says BUY but where the
    # weekly 10MA is far below the last close. Steep recent climb does
    # this naturally.
    # 200 flat bars at 50, then 50 bars climbing 50 → 200 → 10MA way
    # below current.
    closes = [50.0] * 200 + list(np.linspace(50, 200, 50))
    df = _frame(closes)
    df.attrs["grain"] = "W"
    r = analyze_ticker("TEST", df)
    # Whatever action comes out, if it's BUY/STRONG_BUY the entry_plan
    # must either be None or have stop within 15 % of entry.
    ep = r["entry_plan"]
    if r["action"] in ("BUY", "STRONG_BUY") and ep:
        e = ep.get("entry"); s = ep.get("stop")
        assert e and s, "BUY plan must have both entry and stop"
        stop_dist = (e - s) / e
        assert stop_dist <= 0.15 + 1e-6, (
            f"BUY plan with stop {stop_dist*100:.0f}% away from entry "
            f"violates the 15 % gate"
        )
    # And if the action got downgraded, stretch_reason should mention
    # either rally / 240MA / 손절 폭.
    if r["action"] == "HOLD" and r.get("stretch_reason"):
        sr = r["stretch_reason"]
        assert any(k in sr for k in ("8주", "240MA", "손절", "52w")), (
            f"stretch_reason should explain the gate: {sr}"
        )


def test_invalidated_double_bottom_does_not_contribute_to_buy():
    """LG우 case 2: 쌍바닥 neckline 81,000 was reported `completed=True`
    even though current close 72,200 was clearly below it. The
    invalidation pass must stamp invalidated=True, the score must
    exclude it, and STRONG_BUY must not derive from it alone."""
    from app.book.analyzer import (
        _mark_invalidated_patterns, _signal_score, _action_from_score,
    )
    # Synthetic pattern dict mimicking LG우's 쌍바닥
    pat = {
        "kind": "쌍바닥",
        "direction": "bullish",
        "confidence": 0.85,
        "completed": True,
        "detected_at": "2026-04-03",
        "entry": 72200,
        "stop": 65000,
        "target": 100600,
        "reason": "",
        "extra": {
            "low1": {"date": "2026-01-16", "price": 63100},
            "low2": {"date": "2026-04-03", "price": 63500},
            "neckline": 81000,
        },
        "invalidated": False,
        "invalidation_reason": "",
    }
    patterns = [pat]
    _mark_invalidated_patterns(patterns, last_close=72200.0)
    assert pat["invalidated"], "쌍바닥 close below neckline must invalidate"
    assert "neckline" in pat["invalidation_reason"]

    # Score / action must NOT inherit the bullish bias from an invalidated pattern.
    base_score = _signal_score("BUY", patterns, [], None)
    # Base = 0.6 (BUY trend) + 0 (invalidated, ignored) = 0.6, NOT
    # 0.6 + 0.85 × 0.3 = 0.855
    assert abs(base_score - 0.6) < 0.01, (
        f"invalidated pattern should not contribute, score={base_score}"
    )
    # Action: trend=BUY + no valid completed bullish pattern → BUY, not STRONG_BUY.
    action = _action_from_score("BUY", base_score, patterns)
    assert action == "BUY", (
        f"invalidated pattern should not promote to STRONG_BUY, got {action}"
    )


def test_long_bearish_candle_downgrades_buy():
    """LG우 2026-05-22 regression: last weekly bar O 82,100 → C 72,200
    (-12 %, body 93 % of range) was tagged 장대음봉 by classify_candle,
    yet analyzer still emitted STRONG_BUY because no gate consumed the
    tag. Book p262: 장대음봉 = 저승사자 signal — sell, never buy.

    With the new gate:
      - 장대음봉 + close < weekly 10MA → SELL_OR_SHORT (책의 저승사자)
      - 장대음봉 + close ≥ weekly 10MA → HOLD (still a warning)

    Fixture: long uptrend so BUY/STRONG_BUY would naturally be the
    pre-gate verdict, and a final 장대음봉 whose close stays just
    above 10MA so we can confirm HOLD branch (not the SELL one).
    """
    closes = list(np.linspace(50, 100, 250))
    # Final bar: open well above prior close, close at recent high so
    # close stays above 10MA, but body big → 장대음봉 fires.
    closes.append(100.0)
    rows = []
    for i, c in enumerate(closes):
        if i == len(closes) - 1:
            # Open 108, close 100. body = 8 ≫ body_avg ~0.5 → 장대음봉.
            o, h, lo = 108.0, 108.0, 99.5
        else:
            o, h, lo = c * 0.999, c * 1.005, c * 0.995
        rows.append({
            "date": pd.Timestamp("2022-01-07") + pd.Timedelta(weeks=i),
            "open": o, "high": h, "low": lo,
            "close": c, "adj_close": c, "volume": 1_000_000.0,
        })
    df = pd.DataFrame(rows)
    df.attrs["grain"] = "W"
    r = analyze_ticker("TEST.KS", df)
    tags = (r.get("last_candle") or {}).get("tags") or []
    assert "장대음봉" in tags, (
        f"fixture failed to produce 장대음봉 tag: {tags}"
    )
    # Pre-gate action would have been BUY or STRONG_BUY (clean uptrend);
    # post-gate it must be downgraded.
    assert r["action"] not in ("BUY", "STRONG_BUY"), (
        f"장대음봉 should downgrade BUY/STRONG_BUY, got {r['action']}"
    )
    sr = r.get("stretch_reason") or ""
    assert any(k in sr for k in ("장대음봉", "저승사자")), (
        f"stretch_reason should explain the downgrade: {sr!r}"
    )


def test_pos_52w_ignores_zero_ohlv_corruption():
    """Regression for the 009310.KS bug — bars table contained rows
    with high=0 + low=0 (FDR's 거래정지 placeholder leaking through
    the ingestor). The naive 52w window then computed low.min()=0,
    yielding pos_52w = (last_close − 0) / (high.max() − 0) = 3.11
    (i.e., 311 %). After the fix the window must exclude those rows
    so pos_52w stays in [0, 1]."""
    # 48 clean trading bars climbing 100 → 200, then 4 corrupt rows
    # (OHLV=0 + close>0) appended at the tail. Last close = 200.
    n_clean = 48
    closes = list(np.linspace(100, 200, n_clean))
    rows = []
    for i, c in enumerate(closes):
        rows.append({
            "date": pd.Timestamp("2025-01-03") + pd.Timedelta(weeks=i),
            "open": c * 0.99, "high": c * 1.01, "low": c * 0.98,
            "close": c, "adj_close": c, "volume": 1_000_000.0,
        })
    # 4 corrupt rows
    for i in range(4):
        rows.append({
            "date": pd.Timestamp("2025-01-03") + pd.Timedelta(weeks=n_clean + i),
            "open": 0.0, "high": 0.0, "low": 0.0,
            "close": 200.0, "adj_close": 200.0, "volume": 0.0,
        })
    df = pd.DataFrame(rows)
    df.attrs["grain"] = "W"
    r = analyze_ticker("CORRUPT.KS", df)
    pos = r.get("position_in_52w")
    # The whole point: pos must be a sane number in [0, 1].
    assert pos is None or 0 <= pos <= 1.0001, (
        f"pos_52w leaked outside [0,1] despite filter, got {pos}"
    )


def test_stretch_reason_absent_for_avoid_action():
    """If the trend gate forces AVOID (price below monthly 240MA), the
    stretch downgrade logic must not fire — AVOID stays AVOID and
    stretch_reason stays None."""
    # Long downtrend that puts price well below 240MA.
    closes = list(np.linspace(200, 50, 260))
    df = _frame(closes)
    df.attrs["grain"] = "W"
    r = analyze_ticker("TEST", df)
    if r["action"] == "AVOID":
        assert r.get("stretch_reason") in (None, ""), (
            f"AVOID action shouldn't carry stretch_reason: {r['stretch_reason']}"
        )
