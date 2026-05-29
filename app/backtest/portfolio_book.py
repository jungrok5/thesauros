"""Book-faithful portfolio simulator (2026-05-29).

Replaces the "brainless 24-week hold + maybe %-stop" simulator
(portfolio.simulate) with one that exits ONLY on the book's three
canonical signals:

  1. 종목별 월봉 10MA 깨짐 — monthly close below 10-month moving average
     (book's primary trend gauge; 5y / 30,000h author conclusion).
  2. 장대양봉 4등분선 25% 깨짐 — weekly close drops below
     entry_open + 0.25 × (entry_close − entry_open). Only applies when
     the entry bar is bullish; bearish-bar entries fall back to (1)+(3).
  3. 천장 패턴 — pattern_double_top / pattern_triple_top /
     pattern_head_and_shoulders / action_sell / action_sell_short
     fires for the held ticker. Passed in via exit_fires.

No 24-week forced exit. No fixed % stop. No fixed take-profit.
Position closes on the FIRST of (1)/(2)/(3) firing — or marks to
market at end_date if none fires.

Capital allocation: cash / max_positions per BUY (same as the prior
simulator). max is a sweep parameter, not a hardcoded 50.

See memory/project_book_faithful_backtest.md for the architectural
rationale (single algorithm shared by screener / Telegram / backtest).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from app.backtest.portfolio import (
    Position, Trade, PortfolioState,
    _BUY_COST_PCT, _SELL_COST_PCT,
)

log = logging.getLogger("backtest.portfolio_book")


from app.book.exits import (
    is_jangdae_yangbong,
    quartile_25_level,
    LONG_BULLISH_BODY_MULT as _BOOK_BODY_MULT,    # imported for clarity
    LONG_BULLISH_AVG_WINDOW as _BOOK_AVG_WINDOW,
    MONTHLY_MA_WINDOW as _MONTHLY_MA_WINDOW,
)


# ─────────────────────────────────────────────────────────────────────
# Per-ticker bar cache (loaded once via app.backtest.local_store).
# ─────────────────────────────────────────────────────────────────────
_WEEKLY_CACHE: Dict[str, pd.DataFrame] = {}
_MONTHLY_CACHE: Dict[str, pd.DataFrame] = {}


def _weekly_bars(ticker: str) -> pd.DataFrame:
    if ticker not in _WEEKLY_CACHE:
        from app.backtest.local_store import load_bars
        _WEEKLY_CACHE[ticker] = load_bars(ticker, "W")
    return _WEEKLY_CACHE[ticker]


def _monthly_bars(ticker: str) -> pd.DataFrame:
    if ticker not in _MONTHLY_CACHE:
        from app.backtest.local_store import load_bars
        _MONTHLY_CACHE[ticker] = load_bars(ticker, "M")
    return _MONTHLY_CACHE[ticker]


def reset_caches() -> None:
    _WEEKLY_CACHE.clear()
    _MONTHLY_CACHE.clear()


# ─────────────────────────────────────────────────────────────────────
# Exit event builders
# ─────────────────────────────────────────────────────────────────────
def _build_monthly_10ma_exit_events(
    candidates: Sequence[Dict[str, Any]],
    start_date: date,
    end_date: date,
) -> List[Tuple[date, str, str, float, int, float]]:
    """For each candidate, find the FIRST monthly bar after entry where
    close drops below the 10-month MA. Emits (date, EXIT_10MA, ticker,
    close, -1, 0.0). Monthly 10MA is computed on the full ticker series
    so warmup before start_date is automatic.
    """
    out: List[Tuple[date, str, str, float, int, float]] = []
    ma_cache: Dict[str, pd.DataFrame] = {}
    for c in candidates:
        ticker = c["ticker"]
        entry_d = date.fromisoformat(c["entry_date"])
        if entry_d > end_date or entry_d < start_date:
            continue
        if ticker not in ma_cache:
            bars = _monthly_bars(ticker)
            if bars.empty:
                ma_cache[ticker] = pd.DataFrame()
                continue
            ma_cache[ticker] = bars.assign(
                ma10=bars["close"].rolling(_MONTHLY_MA_WINDOW).mean(),
            )
        df = ma_cache[ticker]
        if df.empty:
            continue
        dates = df["date"].dt.date
        # Look at monthly closes STRICTLY AFTER entry (don't immediately
        # exit on the same month we entered).
        mask = (dates > entry_d) & (dates <= end_date)
        window = df.loc[mask].dropna(subset=["ma10"])
        if window.empty:
            continue
        breach_mask = window["close"] < window["ma10"]
        if not breach_mask.any():
            continue
        first = window.loc[breach_mask].iloc[0]
        out.append((
            first["date"].date(), "EXIT_10MA",
            ticker, float(first["close"]), -1, 0.0,
        ))
    return out


# 장대양봉 정의 + 25% level 계산은 app.book.exits 가 single source.
# backtest 와 telegram alerter 가 같은 정의를 공유한다.


def _build_quartile_exit_events(
    candidates: Sequence[Dict[str, Any]],
    start_date: date,
    end_date: date,
) -> List[Tuple[date, str, str, float, int, float]]:
    """For each candidate whose entry bar qualifies as a 장대양봉
    per the book engine definition (app/book/candles.py:172) — body
    ≥ rolling-20 avg body × 2.0 AND close > open — anchor the 4등분
    body on it. Book p218-223 explicitly says the 4등분 technique
    applies to a 장대양봉 catalyst.

    Why book engine's definition: it normalizes to the ticker's recent
    volatility, so a 3% bar in a stable large-cap can qualify while a
    3% bar in a noisy small-cap may not. Absolute thresholds (e.g.,
    fixed 5% gain) systematically over-fire on volatile names and
    under-fire on calm ones — exactly the bias the book engine's
    relative rule avoids.
    """
    out: List[Tuple[date, str, str, float, int, float]] = []
    for c in candidates:
        ticker = c["ticker"]
        entry_d = date.fromisoformat(c["entry_date"])
        if entry_d > end_date or entry_d < start_date:
            continue
        bars = _weekly_bars(ticker)
        if bars.empty:
            continue
        bars_dates = bars["date"].dt.date
        anchor_mask = bars_dates == entry_d
        if not anchor_mask.any():
            continue
        anchor_idx = int(bars.index[anchor_mask][0])
        anchor = bars.iloc[anchor_idx]
        a_open = float(anchor["open"])
        a_close = float(anchor["close"])
        # Rolling avg body on PRIOR bars only (no peek at entry bar).
        lo = max(0, anchor_idx - _BOOK_AVG_WINDOW)
        prior = bars.iloc[lo:anchor_idx]
        if prior.empty:
            continue
        avg_body = float((prior["close"] - prior["open"]).abs().mean())
        if not is_jangdae_yangbong(a_open, a_close, avg_body):
            continue
        q25 = quartile_25_level(a_open, a_close)
        window = bars.loc[(bars_dates > entry_d) & (bars_dates <= end_date)]
        if window.empty:
            continue
        breach = window["close"] < q25
        if not breach.any():
            continue
        first = window.loc[breach].iloc[0]
        out.append((
            first["date"].date(), "EXIT_QUARTILE",
            ticker, float(first["close"]), -1, 0.0,
        ))
    return out


# ─────────────────────────────────────────────────────────────────────
# Simulator
# ─────────────────────────────────────────────────────────────────────
def simulate_book_faithful(
    candidates: Sequence[Dict[str, Any]],
    start_date: date,
    end_date: date,
    *,
    initial_cash: float = 100_000_000.0,    # 1억 default (per project
                                            # memory book_faithful_backtest)
    max_positions: int = 20,
    exit_fires: Optional[Sequence[Dict[str, Any]]] = None,
    buy_cost_pct: float = _BUY_COST_PCT,
    sell_cost_pct: float = _SELL_COST_PCT,
) -> PortfolioState:
    """Same event-driven core as portfolio.simulate but without the
    24-week forced SELL. Exits fire only on EXIT_10MA / EXIT_QUARTILE
    / ACTIVE_EXIT (천장 patterns from exit_fires). Any position still
    open at end_date is marked-to-market closed.
    """
    events: List[Tuple[date, str, str, float, int, float]] = []
    cand_lookup: Dict[int, Dict[str, Any]] = {}

    for i, c in enumerate(candidates):
        ed = date.fromisoformat(c["entry_date"])
        if ed < start_date or ed > end_date:
            continue
        cand_lookup[i] = c
        strength = float(c.get("strength", 0.5))
        events.append((ed, "BUY", c["ticker"],
                      float(c["entry_price"]), i, strength))

    # Pre-compute book exits over the filtered candidate set.
    filtered = [cand_lookup[i] for i in cand_lookup]
    events.extend(_build_monthly_10ma_exit_events(filtered, start_date, end_date))
    events.extend(_build_quartile_exit_events(filtered, start_date, end_date))

    exit_sig_lookup: Dict[Tuple[str, str], str] = {}
    if exit_fires:
        for f in exit_fires:
            ed = date.fromisoformat(f["entry_date"])
            if ed < start_date or ed > end_date:
                continue
            events.append((ed, "ACTIVE_EXIT", f["ticker"],
                          float(f["entry_price"]), -1, 0.0))
            exit_sig_lookup[(f["ticker"], f["entry_date"])] = f.get(
                "signal_type", "exit"
            )

    # Event ordering on same date:
    #   ACTIVE_EXIT (천장) → EXIT_10MA → EXIT_QUARTILE → BUY (strength desc)
    def _order(e: Tuple[date, str, str, float, int, float]):
        kind_rank = {
            "ACTIVE_EXIT": 0,
            "EXIT_10MA": 1,
            "EXIT_QUARTILE": 2,
            "BUY": 3,
        }.get(e[1], 4)
        strength_order = -e[5] if e[1] == "BUY" else 0.0
        return (e[0], kind_rank, strength_order)
    events.sort(key=_order)

    state = PortfolioState(cash=initial_cash, initial_cash=initial_cash)

    def _close_position(d: date, ticker: str, price: float,
                        entry_sig: str, exit_sig: str) -> None:
        pos = state.positions.pop(ticker)
        proceeds = pos.shares * price * (1 - sell_cost_pct)
        state.cash += proceeds
        pnl = proceeds - pos.cost_basis_krw
        state.trades.append(Trade(
            ticker=ticker, entry_date=pos.entry_date, exit_date=d,
            entry_price=pos.entry_price, exit_price=price,
            shares=pos.shares, cost_basis_krw=pos.cost_basis_krw,
            proceeds_krw=proceeds, pnl_krw=pnl,
            pnl_pct=(pnl / pos.cost_basis_krw * 100.0)
                    if pos.cost_basis_krw > 0 else 0.0,
            days_held=(d - pos.entry_date).days,
            signal_type=f"{entry_sig}→{exit_sig}" if exit_sig else entry_sig,
        ))
        state.equity_history.append((d, _equity_estimate(state)))

    for d, kind, ticker, price, cand_idx, _strength in events:
        if kind in ("ACTIVE_EXIT", "EXIT_10MA", "EXIT_QUARTILE"):
            if ticker not in state.positions:
                continue
            entry_sig = state.positions[ticker].entry_signal
            if kind == "ACTIVE_EXIT":
                exit_label = exit_sig_lookup.get(
                    (ticker, d.isoformat()), "active_exit"
                )
            elif kind == "EXIT_10MA":
                exit_label = "monthly_10ma_break"
            else:
                exit_label = "quartile_25_break"
            _close_position(d, ticker, price, entry_sig, exit_label)

        elif kind == "BUY":
            if len(state.positions) >= max_positions:
                continue
            if ticker in state.positions:
                continue
            open_slots = max_positions - len(state.positions)
            if open_slots <= 0:
                continue
            allocation = state.cash / open_slots
            if allocation <= 0 or price <= 0:
                continue
            net = allocation / (1 + buy_cost_pct)
            shares = net / price
            cost_basis = allocation
            if shares <= 0:
                continue
            state.cash -= cost_basis
            cand = cand_lookup[cand_idx]
            state.positions[ticker] = Position(
                ticker=ticker, entry_date=d,
                entry_price=price, shares=shares,
                cost_basis_krw=cost_basis,
                exit_date_planned=end_date,   # no 24w plan; placeholder
                entry_signal=cand.get("signal_type", "?"),
            )
            state.equity_history.append((d, _equity_estimate(state)))

    # Mark-to-market remaining positions at end_date.
    from app.backtest.portfolio import _last_close_or_na
    for ticker, pos in list(state.positions.items()):
        final_price = _last_close_or_na(ticker, end_date)
        if final_price is None:
            final_price = pos.entry_price
        proceeds = pos.shares * final_price * (1 - sell_cost_pct)
        state.cash += proceeds
        pnl = proceeds - pos.cost_basis_krw
        state.trades.append(Trade(
            ticker=ticker, entry_date=pos.entry_date, exit_date=end_date,
            entry_price=pos.entry_price, exit_price=final_price,
            shares=pos.shares, cost_basis_krw=pos.cost_basis_krw,
            proceeds_krw=proceeds, pnl_krw=pnl,
            pnl_pct=(pnl / pos.cost_basis_krw * 100.0)
                    if pos.cost_basis_krw > 0 else 0.0,
            days_held=(end_date - pos.entry_date).days,
            signal_type=f"{pos.entry_signal}→forced_close_at_end",
        ))
        del state.positions[ticker]
    state.equity_history.append((end_date, _equity_estimate(state)))
    return state


def _equity_estimate(state: PortfolioState) -> float:
    """Conservative equity = cash + cost basis of open positions.
    Matches portfolio._equity. Final equity after close-out is exact."""
    held = sum(p.cost_basis_krw for p in state.positions.values())
    return state.cash + held
