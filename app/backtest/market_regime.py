"""Market-regime filter for portfolio backtest.

Book principle (책 정신 우선순위 1번): 거시 → 추세 → 패턴.
Individual stock signals fire even in bear markets; the book's
strongest defense against drawdown is to DISABLE buying when the
broader market trend is down.

Indicator: **KOSPI 월봉 10MA** (book's primary trend gauge —
"월봉 10이평선이 바로 객관적 추세선" — p318-319).

  - Above 10MA: bullish regime → BUY allowed.
  - Below 10MA: bearish regime → new BUYs blocked; existing positions
    follow their planned exits.

Why monthly 10MA (not weekly 240MA):
  - Weekly 240MA whipsaws — close runs near the MA for months, with
    1-week regime flips that don't reflect real regime change.
  - Monthly 10MA is the book's canonical trend signal. Transitions
    are slow (~2/year), aligned with the book's "주봉/월봉 결정 단위".
  - Empirically catches GFC 2008 (signal 2008-01-31), COVID 2020-02,
    2022 bear (signal 2021-09-30) — exactly the periods we want
    to filter out.

Storage: KOSPI is ingested into the local DuckDB under ticker "^KS11"
(re-fetched via yfinance daily → resampled weekly + monthly).

Cache: regime timeline is a small (~300 monthly bars) DataFrame,
loaded once per process and kept in module state.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

log = logging.getLogger("backtest.market_regime")

KOSPI_TICKER = "^KS11"
MA_WINDOW = 10           # 10 monthly bars (book's 월봉 10MA)
MA_MIN_PERIODS = 5       # ≥5 months of history before the MA is meaningful

_REGIME_DF: Optional[pd.DataFrame] = None


def _load_regime_df() -> pd.DataFrame:
    """Load + cache the KOSPI MONTHLY bars with 10MA + derived fields.

    Schema: date (month-end), close, ma_10, above (bool),
            below_pct (% below 10MA, 0 if above), ma_10_slope_3m (MA
            change vs 3 months ago — negative = falling).
    Earlier rows have ma_10 = NaN (before MIN_PERIODS).
    """
    global _REGIME_DF
    if _REGIME_DF is not None:
        return _REGIME_DF

    from app.backtest.local_store import load_bars
    df = load_bars(KOSPI_TICKER, "M")
    if df.empty:
        raise RuntimeError(
            f"KOSPI ticker {KOSPI_TICKER!r} missing from local store. "
            "Run `python -c \"from app.backtest.market_regime import "
            "ensure_kospi_loaded; ensure_kospi_loaded()\"`."
        )
    df = df.sort_values("date").reset_index(drop=True)
    df["ma_10"] = df["close"].rolling(
        window=MA_WINDOW, min_periods=MA_MIN_PERIODS,
    ).mean()
    df["above"] = df["close"] > df["ma_10"]
    # Magnitude of being below MA — 0 if at/above, positive % if below.
    df["below_pct"] = ((df["ma_10"] - df["close"]) / df["ma_10"] * 100).clip(lower=0)
    # MA slope: this month's MA vs 3 months ago. Negative = falling.
    df["ma_10_slope_3m"] = df["ma_10"] - df["ma_10"].shift(3)
    _REGIME_DF = df
    log.debug("loaded KOSPI regime: %d monthly bars, %s ~ %s",
              len(df), df["date"].min().date(), df["date"].max().date())
    return df


def clear_regime_cache() -> None:
    """Reset the module-level cache. Used by tests."""
    global _REGIME_DF
    _REGIME_DF = None


def is_market_above_10ma_at(d: date) -> Optional[bool]:
    """KOSPI monthly close above 10-month MA at the latest month-end ≤ `d`?

    Returns:
      - True  if above (BUY allowed)
      - False if below (BUY blocked)
      - None  if MA not yet computable at `d` (early-history fallback —
              caller decides to allow or block; default: allow)
    """
    df = _load_regime_df()
    mask = df["date"].dt.date <= d
    if not mask.any():
        return None
    last = df[mask].iloc[-1]
    if pd.isna(last["ma_10"]):
        return None
    return bool(last["above"])


# Backward-compat alias name (used by callers expecting the old API).
is_market_above_240ma_at = is_market_above_10ma_at


# ─────────────────────────────────────────────────────────────────────
# Convenience: builds a callable for portfolio.simulate(regime_filter=...)
# ─────────────────────────────────────────────────────────────────────

def kospi_regime_filter(allow_unknown: bool = True):
    """Return a callable `(date) → bool` suitable as regime_filter
    for portfolio.simulate(). Wraps the book's 월봉 10MA gate.

    `allow_unknown=True` (default): if KOSPI MA isn't yet computable
    at the date (early history), allow BUY. Conservative alternative
    is to set False — pre-MA dates block BUY (safer but eats early
    history). Default favors more data over over-caution.
    """
    def _filter(d: date) -> bool:
        above = is_market_above_10ma_at(d)
        if above is None:
            return allow_unknown
        return above
    return _filter


# Backward-compat name
kospi_240ma_filter = kospi_regime_filter


# ─────────────────────────────────────────────────────────────────────
# Smart filter — combine magnitude + slope to avoid false-bear blocks
# ─────────────────────────────────────────────────────────────────────

def _regime_state_at(d: date) -> Optional[dict]:
    """Return the latest regime row ≤ d as a dict, or None if no
    valid (post-MA) bar yet."""
    df = _load_regime_df()
    mask = df["date"].dt.date <= d
    if not mask.any():
        return None
    row = df[mask].iloc[-1]
    if pd.isna(row["ma_10"]):
        return None
    return {
        "close": float(row["close"]),
        "ma_10": float(row["ma_10"]),
        "above": bool(row["above"]),
        "below_pct": float(row["below_pct"]),
        "ma_10_slope_3m": float(row["ma_10_slope_3m"])
        if not pd.isna(row["ma_10_slope_3m"]) else None,
    }


def kospi_smart_filter(
    below_threshold_pct: float = 3.0,
    require_falling_ma: bool = True,
    allow_unknown: bool = True,
):
    """Smart KOSPI regime filter — block BUY only on REAL bears.

    A "real bear" requires BOTH:
      (a) close ≥ `below_threshold_pct` below 10MA (default: 3%) —
          rules out small intraprice dips around the MA (책 시장
          consolidation 무시), and
      (b) `require_falling_ma`: 10MA itself trending down (slope of
          MA10 over the last 3 months is negative). This guards against
          single-month flush events during otherwise rising trends.

    Either condition relaxed → fewer blocks → more upside captured
    during 2014/2018-style consolidations.

    Args:
        below_threshold_pct: KOSPI must be at least this % below
            10MA to be considered bearish. 3% empirically catches
            2008 (-10%) / 2020 (-4%) / 2022 (-10%+) while passing
            2018 (-0.6%) / 2014 (small).
        require_falling_ma: also require MA10 itself to be falling.
            Default True.
        allow_unknown: pre-MA history (early KOSPI) — True allows BUY,
            False blocks.

    Returns:
        callable (date) → bool — True = allow BUY, False = block.
    """
    def _filter(d: date) -> bool:
        state = _regime_state_at(d)
        if state is None:
            return allow_unknown
        # Above MA → bull, allow.
        if state["above"]:
            return True
        # Below MA — check magnitude.
        if state["below_pct"] < below_threshold_pct:
            return True   # shallow dip, treat as consolidation
        # Below by meaningful amount — check slope if required.
        if require_falling_ma:
            slope = state["ma_10_slope_3m"]
            if slope is None or slope >= 0:
                return True   # MA still rising → consolidation, allow
        return False   # meaningful AND sustained downtrend → block
    return _filter


def regime_stats() -> dict:
    """Summary stats — how many months above vs below over the full
    KOSPI history."""
    df = _load_regime_df()
    valid = df.dropna(subset=["ma_10"])
    n = len(valid)
    n_above = int(valid["above"].sum())
    return {
        "n_months_total": n,
        "n_months_above_10ma": n_above,
        "n_months_below_10ma": n - n_above,
        "pct_above": n_above / n if n else 0.0,
        "first_valid_date": valid.iloc[0]["date"].date() if n else None,
        "last_date": df.iloc[-1]["date"].date() if len(df) else None,
    }


# ─────────────────────────────────────────────────────────────────────
# One-time KOSPI ingest helper (idempotent)
# ─────────────────────────────────────────────────────────────────────

def ensure_kospi_loaded() -> int:
    """Fetch KOSPI from yfinance, resample to W + M, store under
    ticker '^KS11' in the local DuckDB. Returns rows written.

    Call this once before the first regime lookup if the local store
    doesn't already have KOSPI bars (idempotent — re-runs upsert).
    """
    import yfinance as yf
    from app.backtest.local_store import connect, upsert_bars
    from app.db.ingest_bars import _resample_daily_to_rows

    daily = yf.Ticker(KOSPI_TICKER).history(
        start="2000-01-01", auto_adjust=False,
    )
    daily = daily.reset_index().rename(columns={
        "Date": "date", "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Adj Close": "adj_close", "Volume": "volume",
    })
    if isinstance(daily["date"].dtype, pd.DatetimeTZDtype):
        daily["date"] = daily["date"].dt.tz_convert(None)
    daily["date"] = pd.to_datetime(daily["date"])
    # Drop suspended placeholders.
    suspended = (
        (daily["open"].fillna(0) == 0)
        & (daily["high"].fillna(0) == 0)
        & (daily["low"].fillna(0) == 0)
    )
    if suspended.any():
        daily = daily.loc[~suspended].copy()
    rows = _resample_daily_to_rows(KOSPI_TICKER, daily)
    df = pd.DataFrame(rows, columns=[
        "ticker", "granularity", "bar_date",
        "open", "high", "low", "close", "adj_close", "volume",
    ])
    with connect() as conn:
        return upsert_bars(conn, KOSPI_TICKER, df)
