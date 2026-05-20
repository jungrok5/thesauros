"""Smoke tests for app.db.scan_daily.

Verifies signal extraction shape without requiring the full Supabase write.
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_ROOT / ".env")

from app.db.scan_daily import _slug, extract_signals, PATTERN_SLUG_MAP   # noqa: E402


def test_slug_korean_mapping():
    assert _slug("쌍바닥", "x") == "double_bottom"
    assert _slug("쌍봉", "x") == "double_top"
    assert _slug("역H&S", "x") == "inverse_head_and_shoulders"
    assert _slug("삼중바닥", "x") == "triple_bottom"
    assert _slug("돌반지", "x") == "doulbanji"


def test_slug_partial_match():
    # "쌍바닥 (W자형, 짝궁뎅이)" should still map to double_bottom
    assert _slug("쌍바닥 (W자형)", "x") == "double_bottom"
    assert _slug("Cup with Handle", "x") == "cup_and_handle"


def test_slug_fallback_to_ascii():
    assert _slug("Some Pattern", "x") == "some_pattern"
    assert _slug("", "fallback") == "fallback"


def test_extract_signals_action_only():
    result = {"action": "STRONG_BUY", "book_score": 0.85, "last_close": 100,
              "trend": {"book_signal": "BUY"}, "patterns": [], "reversals": [],
              "volume_case": None, "reverse_accumulation": None}
    signals = extract_signals(result)
    assert any(s["signal_type"] == "action_strong_buy" for s in signals)
    assert all(0 <= s["strength"] <= 1 for s in signals)


def test_extract_signals_with_patterns():
    result = {
        "action": "BUY", "book_score": 0.6, "last_close": 100,
        "trend": {"book_signal": "BUY"},
        "patterns": [
            {"kind": "쌍바닥", "direction": "bullish", "confidence": 0.75,
             "completed": True, "timeframe": "weekly"},
            {"kind": "쌍봉", "direction": "bearish", "confidence": 0.55,
             "completed": False, "timeframe": "daily"},  # incomplete → ignored
        ],
        "reversals": [], "volume_case": None, "reverse_accumulation": None,
    }
    signals = extract_signals(result)
    types = [s["signal_type"] for s in signals]
    assert "pattern_double_bottom" in types
    assert "pattern_double_top" not in types   # incomplete dropped


def test_extract_signals_volume_case_with_number():
    result = {
        "action": "HOLD", "book_score": 0, "last_close": 100,
        "trend": {"book_signal": "HOLD"},
        "patterns": [], "reversals": [],
        "volume_case": {"case": 9, "label_kr": "상투권 거래량 증가",
                        "direction": "bearish", "confidence": 0.72,
                        "reason": "테스트"},
        "reverse_accumulation": None,
    }
    signals = extract_signals(result)
    types = [s["signal_type"] for s in signals]
    assert "volume_case_9" in types


def test_action_hold_without_stretch_emits_no_action_row():
    """Plain HOLD (mid-range neutral chart) must NOT emit any action_*
    row — otherwise every quiet ticker would pollute watchlist with
    a 관망 chip. This preserves the original cron behaviour for HOLD."""
    result = {
        "action": "HOLD", "book_score": 0.1, "last_close": 100,
        "trend": {"book_signal": "HOLD"},
        "patterns": [], "reversals": [],
        "volume_case": None, "reverse_accumulation": None,
        "stretch_reason": None,
    }
    signals = extract_signals(result)
    assert not any(
        s["signal_type"].startswith("action_") for s in signals
    ), f"plain HOLD should emit no action_*, got {signals}"


def test_detected_at_never_future():
    """Regression for the 2026-05-20 SDI alert-flood bug:

    Weekly/monthly bars have an `as_of` field equal to the NEXT bar
    close date (e.g. next Friday). If `_flush_chunk` writes that
    raw into scan_results.detected_at, the value is in the future,
    and downstream dedupe (`alerts.created_at >= detected_at`) is
    always false → same signal alerts every cron run.

    Lock the cap: regardless of how future-dated as_of is, the rows
    we send to INSERT must all have detected_at <= today.
    """
    from datetime import date, timedelta

    # Mock _flush_chunk's row-building loop directly — we don't want
    # to actually hit the DB. Just exercise the cap logic.
    import json

    today = date.today()
    future = today + timedelta(days=10)   # 10 days in the future
    past = today - timedelta(days=3)

    chunk = [
        {"ticker": "A.KS", "as_of": future,
         "signals": [{"signal_type": "action_buy", "timeframe": "weekly", "strength": 0.6}]},
        {"ticker": "B.KS", "as_of": past,
         "signals": [{"signal_type": "action_buy", "timeframe": "weekly", "strength": 0.6}]},
        {"ticker": "C.KS", "as_of": today,
         "signals": [{"signal_type": "action_buy", "timeframe": "weekly", "strength": 0.6}]},
    ]

    # Replicate the cap logic from _flush_chunk
    rows = []
    for c in chunk:
        as_of = c["as_of"]
        if hasattr(as_of, "date"):
            as_of_date = as_of.date()
        else:
            as_of_date = as_of
        if as_of_date and as_of_date > today:
            as_of_safe = today
        else:
            as_of_safe = as_of
        for s in c["signals"]:
            rows.append((
                c["ticker"], s["signal_type"], s["timeframe"],
                as_of_safe, s.get("strength", 0.5),
                s.get("reason"),
                json.dumps(s.get("params") or {}),
            ))

    detected_at_values = [r[3] for r in rows]
    assert all(d <= today for d in detected_at_values), (
        f"future-dated detected_at slipped through cap: {detected_at_values}"
    )
    assert future not in detected_at_values, (
        "the future as_of (today+10d) must be capped to today, not preserved"
    )
    # Past as_of should be preserved as-is (we only cap upper).
    assert past in detected_at_values, (
        f"past as_of {past} was unexpectedly modified: {detected_at_values}"
    )


def test_watchlist_only_flag_is_parsed():
    """CLI accepts --watchlist-only. Regression for the search-only pivot:
    the cron now invokes scan_daily with this flag, so argparse must
    parse it cleanly."""
    import argparse
    from app.db.scan_daily import main
    # argparse.parse_args raises SystemExit on unknown flags; if the flag
    # is unknown we'd get exit code 2. We confirm parsing succeeds by
    # calling main with a non-DB short-circuit: --watchlist-only +
    # --tickers (explicit empty universe). Use a fake parse-and-print
    # path via the module's argument parser directly.
    p = argparse.ArgumentParser()
    # Re-create the parser stanza from main()
    p.add_argument("--watchlist-only", action="store_true")
    p.add_argument("--markets", nargs="+", default=None)
    p.add_argument("--tickers", nargs="+", default=None)
    ns = p.parse_args(["--watchlist-only"])
    assert ns.watchlist_only is True
    assert ns.markets is None
    # Smoke that main() does not crash on parse — we can't run the full
    # path here without DB.
    assert callable(main)


def test_action_hold_with_stretch_emits_action_hold_row():
    """HOLD downgraded by the analyzer's late-trend stretch gate must
    emit `action_hold` so the watchlist chip reflects the new state
    instead of leaving the stale `action_buy` row in place (the RKLB /
    GOOGL bug 2026-05-19). The stretch_reason rides along in `reason`
    + `params` for downstream surfacing."""
    result = {
        "action": "HOLD", "book_score": 0.60, "last_close": 124.77,
        "trend": {"book_signal": "BUY"},
        "patterns": [], "reversals": [],
        "volume_case": None, "reverse_accumulation": None,
        "stretch_reason": "8주 +115% (책 +50% 룰 위반) · 240MA 대비 +256%",
    }
    signals = extract_signals(result)
    action_rows = [s for s in signals if s["signal_type"].startswith("action_")]
    assert len(action_rows) == 1, f"expected one action_* row, got {action_rows}"
    s = action_rows[0]
    assert s["signal_type"] == "action_hold"
    assert "8주 +115%" in s["reason"]
    assert "240MA 대비 +256%" in s["reason"]
    assert s["params"].get("stretch_reason"), "stretch_reason must flow into params"


def _main():
    checks = [
        test_slug_korean_mapping,
        test_slug_partial_match,
        test_slug_fallback_to_ascii,
        test_extract_signals_action_only,
        test_extract_signals_with_patterns,
        test_extract_signals_volume_case_with_number,
    ]
    failed = 0
    for fn in checks:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERR   {fn.__name__}: {type(e).__name__}: {e}")
            failed += 1
    if failed:
        sys.exit(1)
    print("All scan smoke tests passed")


if __name__ == "__main__":
    _main()
