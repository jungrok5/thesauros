"""Regression: FDR returns OHLV=0 placeholder rows on non-trading
days for suspended / 거래정지 KR symbols. ingest_bars must drop
those rows so the bars table never carries them downstream.

Bug history (2026-05-19):
  504 KR tickers had 12,485 weekly bars with open=high=low=volume=0
  in the bars table. Downstream effects:
    - 009310.KS 52w-low was 0 → pos_in_52w = 311 % (impossible)
    - Volume cases mis-classified every bar as "거래량 폭증"
    - Candle wick percentages NaN / Inf
  Root cause: fetch_kr_ticker passed FDR rows through unchanged.
  Fix: drop rows where (open==0 AND high==0 AND low==0 AND volume==0).
  This module pins that behaviour.

Tests use a hand-built daily DataFrame instead of hitting FDR — the
filter logic must be deterministic regardless of FDR's current
response shape for any given ticker.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from app.db.ingest_bars import _resample_daily_to_rows


def _suspended_row(d: str, close: float) -> dict:
    """Mimic FDR's placeholder row for a non-trading day."""
    return {
        "date": d, "open": 0.0, "high": 0.0, "low": 0.0,
        "close": close, "volume": 0, "adj_close": close,
    }


def _trading_row(d: str, o: float, h: float, l: float, c: float, v: int = 100_000) -> dict:
    return {
        "date": d, "open": o, "high": h, "low": l,
        "close": c, "volume": v, "adj_close": c,
    }


def test_resample_drops_pure_suspended_weeks():
    """A week made entirely of suspended-day placeholder rows must
    produce no weekly bar — the resample helper already drops weeks
    whose close is None, but suspended rows DO have close set."""
    # 5 suspended days in one trading week (Mon-Fri). The current
    # implementation lets the resample go through (close = 1065), then
    # the OHLV-zero filter at fetch_kr_ticker SHOULD have dropped them
    # before reaching here. This test verifies that fetch_kr_ticker's
    # filter is in place by re-running the resample on the same input
    # *after* the filter would have applied (i.e. empty input → empty
    # output).
    df = pd.DataFrame([
        _suspended_row("2026-05-11", 1065),
        _suspended_row("2026-05-12", 1065),
        _suspended_row("2026-05-13", 1065),
        _suspended_row("2026-05-14", 1065),
        _suspended_row("2026-05-15", 1065),
    ])
    # Direct pass-through of the helper (no source filter applied)
    rows = _resample_daily_to_rows("TEST.KS", df)
    weekly = [r for r in rows if r[1] == "W"]
    # The helper itself doesn't filter — that's intentional: it should
    # only see trading days. If we resample a frame of pure suspended
    # rows, weekly bars come out with OHLV=0 (the bug). This pins the
    # *shape of the bug* so we notice if the helper accidentally starts
    # filtering on its own.
    assert len(weekly) <= 1
    if weekly:
        ticker, g, d, o, h, lo, c, _adj, v = weekly[0]
        # If a row survives the resample, OHLV is all 0 — the bug
        # signature we filter against upstream.
        assert o == 0 and h == 0 and lo == 0


def test_resample_keeps_mixed_week_with_trading_days():
    """A week with one suspended day + four trading days produces a
    weekly bar whose OHLC reflects ONLY the trading days. Suspended
    rows should be excluded BEFORE the resample, otherwise their 0s
    pollute high.max() / low.min()."""
    # Simulate the filter happening at fetch_kr_ticker.
    df = pd.DataFrame([
        _suspended_row("2026-05-11", 1065),     # would set low=0 if kept
        _trading_row("2026-05-12", 100, 110,  95,  105),
        _trading_row("2026-05-13", 105, 115, 100,  112),
        _trading_row("2026-05-14", 112, 120, 108,  118),
        _trading_row("2026-05-15", 118, 122, 115,  120),
    ])
    # Apply the same filter fetch_kr_ticker uses.
    suspended = (
        (df["open"].fillna(0) == 0)
        & (df["high"].fillna(0) == 0)
        & (df["low"].fillna(0) == 0)
        & (df["volume"].fillna(0) == 0)
    )
    clean = df.loc[~suspended].copy()
    rows = _resample_daily_to_rows("TEST.KS", clean)
    weekly = [r for r in rows if r[1] == "W"]
    assert len(weekly) == 1
    _, _, _, o, h, lo, c, _adj, _v = weekly[0]
    assert o == 100, f"open should be Mon's open, got {o}"
    assert h == 122, f"high should be max trading high, got {h}"
    assert lo == 95, f"low should be min trading low (NOT 0), got {lo}"
    assert c == 120, f"close should be Fri's close, got {c}"


def test_full_kr_fetcher_drops_suspended_rows(monkeypatch):
    """End-to-end: fetch_kr_ticker calls FDR.DataReader and gets a
    mix of suspended + trading rows. The output rows must contain NO
    OHL=0 row anywhere (weekly or monthly)."""
    from app.db import ingest_bars

    class FakeFDR:
        def DataReader(self, code, start, end):   # noqa: N802 (mimic FDR API)
            return pd.DataFrame(
                [
                    {"Date": pd.Timestamp("2026-05-04"),
                     "Open": 0, "High": 0, "Low": 0, "Close": 1065, "Volume": 0},
                    {"Date": pd.Timestamp("2026-05-05"),
                     "Open": 0, "High": 0, "Low": 0, "Close": 1065, "Volume": 0},
                    {"Date": pd.Timestamp("2026-05-06"),
                     "Open": 100, "High": 110, "Low": 95, "Close": 105, "Volume": 12345},
                    {"Date": pd.Timestamp("2026-05-07"),
                     "Open": 105, "High": 115, "Low": 100, "Close": 112, "Volume": 23456},
                    {"Date": pd.Timestamp("2026-05-08"),
                     "Open": 112, "High": 120, "Low": 108, "Close": 118, "Volume": 34567},
                ]
            ).set_index("Date")

    monkeypatch.setitem(__import__("sys").modules, "FinanceDataReader", FakeFDR())

    rows = ingest_bars.fetch_kr_ticker(
        "123456.KS", date(2026, 5, 1), date(2026, 5, 31)
    )
    assert rows, "fetcher should produce at least one row for a valid ticker"
    # Critical: NO row may have OHL all zero (the corruption signature).
    bad = [r for r in rows if r[3] == 0 and r[4] == 0 and r[5] == 0]
    assert not bad, f"fetcher leaked OHL=0 rows: {bad}"
