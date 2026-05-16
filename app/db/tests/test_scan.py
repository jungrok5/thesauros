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
