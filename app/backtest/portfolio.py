"""Portfolio backtest — Phase 4 (책 정신 + 비용 모델 + 동시 보유).

The "does it actually make money?" answer. Phase 2-3 verified that
signals predict direction (book ↔ data + signal ↔ direction). This
module simulates a portfolio FOLLOWING those signals with realistic
constraints and reports net P&L.

Key differences vs single_signal / sweep:
  - **Concurrent positions**: max N held at once. Cash split.
  - **Transaction costs**: KR 매수 0.015%, 매도 0.18%.
  - **Mark-to-market equity curve**: weekly snapshot of total assets.
  - **Trade journal**: per-trade P&L in 원 + %.
  - **Benchmark**: KOSPI buy-and-hold for the same period.

MVP scope:
  - Fixed hold (N weeks) — no active exit signals (Phase 4.5 adds those)
  - Equal cash split across open slots
  - Top-N entry signals from Phase 3 sweep findings
  - No taxes (most retail KR investors are exempt under threshold)

Usage:
    python -m app.backtest.portfolio --sample 100 \\
        --start 2022-01-01 --end 2025-12-31 \\
        --max-positions 10 --hold-weeks 8 \\
        --initial-cash 10000000 \\
        --entry-signals action_strong_buy pattern_triple_bottom \\
        --csv portfolio_trades.csv
"""
from __future__ import annotations

import argparse
import csv
import logging
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.backtest.sweep import walk_ticker_collect_fires    # noqa: E402
from app.backtest.single_signal import load_weekly_bars     # noqa: E402
from app.db.scan_daily import _list_tickers                 # noqa: E402

log = logging.getLogger("backtest.portfolio")


# Default entry-signal whitelist — tuned from Phase 3 sweep findings.
# These are bullish signals with payoff > 1.5 and win_rate ≥ 45% in
# the 30-ticker sample. Override with --entry-signals on the CLI.
DEFAULT_ENTRY_SIGNALS = (
    "action_strong_buy",
    "action_buy",
    "pattern_triple_bottom",
    "pattern_double_bottom",
    "pattern_ma240_breakout",
    "pattern_rounding_bottom",   # cup-and-handle (V-recovery variant)
    "pattern_inverse_head_and_shoulders",
    "volume_case_7",             # 책 "급등초기거래량증가" — strong buy
)

# Default exit-signal whitelist — bearish fires that should trigger
# ACTIVE EXIT (close held position immediately, don't wait for hold
# expiry). Book p260-265: 쌍봉/저승사자 / 10MA 깨짐 = 즉시 청산.
DEFAULT_EXIT_SIGNALS = (
    "action_sell",
    "action_sell_short",
    "pattern_double_top",
    "pattern_triple_top",
    "pattern_head_and_shoulders",
    "pattern_death_messenger",
)

# KR cost model (retail) — single-direction.
_BUY_COST_PCT = 0.00015      # 0.015% (broker fee)
_SELL_COST_PCT = 0.0018      # 0.18% (broker 0.015% + 거래세 ~0.165%)


@dataclass
class Position:
    """An open long position."""
    ticker: str
    entry_date: date
    entry_price: float
    shares: float
    cost_basis_krw: float          # cash paid INCLUDING fees
    exit_date_planned: date        # for fixed-hold MVP
    entry_signal: str = "?"        # what triggered the buy (for trade journal)


@dataclass
class Trade:
    """A closed round-trip."""
    ticker: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    shares: float
    cost_basis_krw: float
    proceeds_krw: float            # cash received AFTER sell fee
    pnl_krw: float
    pnl_pct: float                 # vs cost_basis
    days_held: int
    signal_type: str               # what triggered the entry


@dataclass
class PortfolioState:
    cash: float
    initial_cash: float
    positions: Dict[str, Position] = field(default_factory=dict)
    trades: List[Trade] = field(default_factory=list)
    equity_history: List[Tuple[date, float]] = field(default_factory=list)


def load_fires_csv(path: Path) -> List[Dict[str, Any]]:
    """Load a per-fire CSV (produced by `sweep --csv`) back into the
    dict-of-dicts shape collect_universe_fires returns. Use this to
    skip the ~14-minute walk when you've already swept the universe.
    """
    rows: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            # Cast numeric columns back to float.
            for k in ("strength", "entry_price", "exit_price",
                      "return_pct", "effective_return_pct"):
                if k in r and r[k] != "":
                    r[k] = float(r[k])
            if "hold_weeks" in r and r["hold_weeks"] != "":
                r["hold_weeks"] = int(r["hold_weeks"])
            rows.append(r)
    return rows


def collect_universe_fires(
    universe: List[str], hold_weeks: int,
) -> List[Dict[str, Any]]:
    """Run sweep across the universe. Each fire becomes a candidate
    trade (one (ticker, entry_date) pair, with planned exit at
    entry_idx + hold_weeks).

    De-duplicates: a single (ticker, entry_date) entry only appears
    once even if multiple signals fired at that bar.
    """
    all_fires: List[Dict[str, Any]] = []
    t0 = time.time()
    for j, t in enumerate(universe, start=1):
        if j % 20 == 0 or j == len(universe):
            log.info("collect fires [%d/%d] %s — %.0fs elapsed, %d fires so far",
                     j, len(universe), t, time.time() - t0, len(all_fires))
        try:
            all_fires.extend(walk_ticker_collect_fires(t, hold_weeks))
        except Exception as e:
            log.warning("ticker %s sweep failed: %s", t, e)
    return all_fires


def filter_exit_fires(
    fires: Sequence[Dict[str, Any]],
    exit_signals: Sequence[str],
) -> List[Dict[str, Any]]:
    """Keep only fires whose signal_type is in the exit-signal
    whitelist AND direction is bearish. Each fire becomes a potential
    ACTIVE EXIT trigger — sorted by date with deduplication on
    (ticker, fire_date) so a single bar's bearish signals (e.g., both
    pattern_double_top AND action_sell_short) trigger one exit, not two.

    The fire's `entry_price` (sweep's close at fire time) is what the
    portfolio sells AT. Treat each fire as a (ticker, sell_date,
    sell_price) tuple regardless of the original 8-week exit it had.
    """
    sig_set = set(exit_signals)
    keep = [
        f for f in fires
        if f.get("signal_type") in sig_set and f.get("direction") == "bearish"
    ]
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for f in keep:
        key = (f["ticker"], f["entry_date"])
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    out.sort(key=lambda f: f["entry_date"])
    return out


def filter_entry_fires(
    fires: Sequence[Dict[str, Any]],
    entry_signals: Sequence[str],
) -> List[Dict[str, Any]]:
    """Keep only fires whose signal_type is in the entry-signal
    whitelist AND direction is bullish. Dedup (ticker, entry_date)
    — if both action_strong_buy and pattern_double_bottom fire at
    the same bar, count once (avoid double-counting one chart event)."""
    sig_set = set(entry_signals)
    keep = [
        f for f in fires
        if f.get("signal_type") in sig_set and f.get("direction") == "bullish"
    ]
    # Dedup
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for f in keep:
        key = (f["ticker"], f["entry_date"])
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    out.sort(key=lambda f: f["entry_date"])
    return out


def simulate(
    candidates: Sequence[Dict[str, Any]],
    start_date: date,
    end_date: date,
    initial_cash: float = 10_000_000.0,
    max_positions: int = 10,
    buy_cost_pct: float = _BUY_COST_PCT,
    sell_cost_pct: float = _SELL_COST_PCT,
    regime_filter: Optional[callable] = None,
    exit_fires: Optional[Sequence[Dict[str, Any]]] = None,
) -> PortfolioState:
    """Replay buy/sell events chronologically.

    Each candidate fire is (entry_date, ticker, entry_price, exit_date,
    exit_price). We convert to a paired event list, sort by date, and
    walk:
      - BUY: if slot open AND ticker not held AND have cash AND regime
        allows, take it
      - SELL: if held, close (regime doesn't gate sells — let positions
        exit naturally even in bear regimes)

    `regime_filter(date) → bool`: if provided, called on each BUY event
    date. False blocks the BUY (cash stays, slot stays open). Defaults
    to None (no filter — current Phase 4 behavior).
    See app/backtest/market_regime.py for the KOSPI 월봉 10MA filter.

    `exit_fires`: bearish-signal fires (from filter_exit_fires).
    When one fires while a position is held, the position closes
    IMMEDIATELY at the fire's price. The planned 8-week exit becomes
    a no-op. Book p260-265: 쌍봉/저승사자 / 10MA 깨짐 = 즉시 청산.

    Equity is recorded at every event date AND at end_date.
    """
    # Build event list:
    #   (date, kind, ticker, price, candidate_idx, strength)
    # candidate_idx = -1 for ACTIVE_EXIT events (not from `candidates`).
    # strength = 0.0 for non-BUY events (only matters for BUY ordering).
    events: List[Tuple[date, str, str, float, int, float]] = []
    for i, c in enumerate(candidates):
        ed = date.fromisoformat(c["entry_date"])
        xd = date.fromisoformat(c["exit_date"])
        if ed > end_date or xd < start_date:
            continue
        if ed < start_date:
            continue                 # entry too early — skip (no warmup yet)
        strength = float(c.get("strength", 0.5))
        events.append((ed, "BUY", c["ticker"], c["entry_price"], i, strength))
        # exit at xd, but capped at end_date (mark-to-market close-out)
        actual_exit = min(xd, end_date)
        actual_exit_price = c["exit_price"] if xd <= end_date else _last_close_or_na(
            c["ticker"], end_date
        )
        if actual_exit_price is None:
            continue
        events.append((actual_exit, "SELL", c["ticker"], actual_exit_price, i, 0.0))

    # Active-exit events from bearish signals.
    if exit_fires:
        for f in exit_fires:
            ed = date.fromisoformat(f["entry_date"])
            if ed < start_date or ed > end_date:
                continue
            events.append((ed, "ACTIVE_EXIT", f["ticker"],
                          f["entry_price"], -1, 0.0))

    # Sort order at each date:
    #   1. ACTIVE_EXIT  (free held slots first)
    #   2. SELL         (planned exits)
    #   3. BUY          (new entries — by strength DESC: strongest wins
    #                   the slot when same-day fires compete)
    #
    # Phase 4.6 priority: in 100-ticker 17yr sweep, action_strong_buy
    # had sweep payoff 2.05 (best) but portfolio-only -14% (essentially
    # break-even) because max_positions=10 fills early with weaker
    # signals (action_buy, pattern_double_bottom). Sorting BUY by
    # strength desc lets the strongest signal claim the slot first.
    def _event_order(e):
        kind = e[1]
        kind_order = {"ACTIVE_EXIT": 0, "SELL": 1, "BUY": 2}.get(kind, 3)
        # strength desc within BUY (negative for ascending sort).
        strength_order = -e[5] if kind == "BUY" else 0.0
        return (e[0], kind_order, strength_order)
    events.sort(key=_event_order)

    state = PortfolioState(cash=initial_cash, initial_cash=initial_cash)
    cand_lookup = {i: c for i, c in enumerate(candidates)}
    # Index exit_fires by (ticker, date) for fast lookup of the
    # triggering signal_type on ACTIVE_EXIT events.
    exit_sig_lookup: Dict[Tuple[str, str], str] = {}
    if exit_fires:
        for f in exit_fires:
            exit_sig_lookup[(f["ticker"], f["entry_date"])] = f.get(
                "signal_type", "exit"
            )

    def _close_position(event_date: date, ticker: str, price: float,
                        entry_signal: str, exit_signal: str) -> None:
        """Sell a held position and record the Trade. Shared by both
        planned SELL and ACTIVE_EXIT paths."""
        pos = state.positions.pop(ticker)
        proceeds = pos.shares * price * (1 - sell_cost_pct)
        state.cash += proceeds
        pnl = proceeds - pos.cost_basis_krw
        state.trades.append(Trade(
            ticker=ticker,
            entry_date=pos.entry_date,
            exit_date=event_date,
            entry_price=pos.entry_price,
            exit_price=price,
            shares=pos.shares,
            cost_basis_krw=pos.cost_basis_krw,
            proceeds_krw=proceeds,
            pnl_krw=pnl,
            pnl_pct=(pnl / pos.cost_basis_krw * 100.0)
                    if pos.cost_basis_krw > 0 else 0.0,
            days_held=(event_date - pos.entry_date).days,
            signal_type=(
                f"{entry_signal}→{exit_signal}"
                if exit_signal else entry_signal
            ),
        ))
        state.equity_history.append((event_date, _equity(state)))

    for event_date, kind, ticker, price, cand_idx, _strength in events:
        if kind == "ACTIVE_EXIT":
            if ticker not in state.positions:
                continue   # nothing to close (not held)
            exit_sig = exit_sig_lookup.get(
                (ticker, event_date.isoformat()), "active_exit"
            )
            entry_sig = state.positions[ticker].entry_signal
            _close_position(event_date, ticker, price, entry_sig, exit_sig)

        elif kind == "SELL":
            if ticker not in state.positions:
                continue   # already closed by active exit
            cand = cand_lookup[cand_idx]
            _close_position(event_date, ticker, price,
                            cand.get("signal_type", "?"), "")

        elif kind == "BUY":
            if len(state.positions) >= max_positions:
                continue
            if ticker in state.positions:
                continue
            if regime_filter is not None and not regime_filter(event_date):
                # Market regime says no — skip BUY, keep cash + slot.
                continue
            open_slots = max_positions - len(state.positions)
            if open_slots <= 0:
                continue
            allocation = state.cash / open_slots
            if allocation <= 0 or price <= 0:
                continue
            # Pay buy fee from allocation; shares from net.
            net = allocation / (1 + buy_cost_pct)
            shares = net / price
            cost_basis = allocation         # cash leaving
            if shares <= 0:
                continue
            state.cash -= cost_basis
            cand = cand_lookup[cand_idx]
            state.positions[ticker] = Position(
                ticker=ticker,
                entry_date=event_date,
                entry_price=price,
                shares=shares,
                cost_basis_krw=cost_basis,
                exit_date_planned=date.fromisoformat(cand["exit_date"]),
                entry_signal=cand.get("signal_type", "?"),
            )
            state.equity_history.append((event_date, _equity(state)))

    # Final mark-to-market: close any still-open positions at end_date.
    for ticker, pos in list(state.positions.items()):
        final_price = _last_close_or_na(ticker, end_date)
        if final_price is None:
            final_price = pos.entry_price        # conservative: assume flat
        proceeds = pos.shares * final_price * (1 - sell_cost_pct)
        state.cash += proceeds
        pnl = proceeds - pos.cost_basis_krw
        state.trades.append(Trade(
            ticker=ticker, entry_date=pos.entry_date, exit_date=end_date,
            entry_price=pos.entry_price, exit_price=final_price,
            shares=pos.shares, cost_basis_krw=pos.cost_basis_krw,
            proceeds_krw=proceeds, pnl_krw=pnl,
            pnl_pct=(pnl / pos.cost_basis_krw * 100.0) if pos.cost_basis_krw > 0 else 0.0,
            days_held=(end_date - pos.entry_date).days,
            signal_type="forced_close_at_end",
        ))
        del state.positions[ticker]
    state.equity_history.append((end_date, _equity(state)))
    return state


_last_close_cache: Dict[Tuple[str, date], Optional[float]] = {}


def _last_close_or_na(ticker: str, on_or_before: date) -> Optional[float]:
    """Last weekly close for ticker on or before given date. Cached
    per (ticker, date) so we don't re-pull bars every call."""
    key = (ticker, on_or_before)
    if key in _last_close_cache:
        return _last_close_cache[key]
    try:
        df = load_weekly_bars(ticker)
    except Exception:
        _last_close_cache[key] = None
        return None
    if df is None or df.empty:
        _last_close_cache[key] = None
        return None
    df_until = df[df["date"].dt.date <= on_or_before]
    if df_until.empty:
        _last_close_cache[key] = None
        return None
    val = float(df_until.iloc[-1]["close"])
    _last_close_cache[key] = val
    return val


def _equity(state: PortfolioState) -> float:
    """Current total equity (cash only; for true MTM, would need
    current price of each open position)."""
    # MVP: equity = cash + cost_basis sum (positions valued at cost).
    # This is conservative — actual price might be higher. Final
    # equity after all positions close is exact.
    held_cost = sum(p.cost_basis_krw for p in state.positions.values())
    return state.cash + held_cost


def summarize(state: PortfolioState) -> Dict[str, Any]:
    """Stats: total return, win rate, avg P&L, max drawdown, Sharpe."""
    if not state.trades:
        return {"n_trades": 0, "final_equity": state.cash}
    final = state.cash
    total_return_pct = (final / state.initial_cash - 1) * 100.0
    pnls = [t.pnl_pct for t in state.trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    avg_win = statistics.mean(wins) if wins else 0.0
    avg_loss = statistics.mean(losses) if losses else 0.0
    # Max drawdown on equity_history.
    peak = state.initial_cash
    max_dd = 0.0
    for _, eq in state.equity_history:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return {
        "n_trades": len(state.trades),
        "n_tickers_traded": len({t.ticker for t in state.trades}),
        "initial_cash": state.initial_cash,
        "final_equity": final,
        "total_return_pct": total_return_pct,
        "win_rate": len(wins) / len(pnls),
        "avg_pnl_pct": statistics.mean(pnls),
        "median_pnl_pct": statistics.median(pnls),
        "best_trade_pct": max(pnls),
        "worst_trade_pct": min(pnls),
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "payoff": (avg_win / abs(avg_loss)) if wins and losses else None,
        "max_drawdown_pct": max_dd * 100.0,
    }


def _print_summary(stats: Dict[str, Any]) -> None:
    print()
    print("=" * 70)
    print("PORTFOLIO BACKTEST SUMMARY")
    print("=" * 70)
    _ratio_keys = {"win_rate", "payoff"}
    for k, v in stats.items():
        if isinstance(v, float):
            if "pct" in k or k == "win_rate":
                print(f"  {k:25s} {v:>10.2f}")
            elif k == "payoff":
                print(f"  {k:25s} {v:>10.2f}")
            else:
                print(f"  {k:25s} {v:>12,.0f}")
        elif v is None:
            print(f"  {k:25s}        -")
        else:
            print(f"  {k:25s} {v:>10}")
    print("=" * 70)


def _save_trades_csv(state: PortfolioState, path: Path) -> None:
    if not state.trades:
        return
    fields = [
        "ticker", "signal_type", "entry_date", "exit_date", "days_held",
        "entry_price", "exit_price", "shares",
        "cost_basis_krw", "proceeds_krw", "pnl_krw", "pnl_pct",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for t in state.trades:
            w.writerow({k: getattr(t, k) for k in fields})


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--tickers", nargs="+", default=None)
    g.add_argument("--sample", type=int, default=None)
    p.add_argument("--sample-seed", type=int, default=42)
    p.add_argument("--market", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--start", required=True, help="ISO date, e.g. 2022-01-01")
    p.add_argument("--end", required=True, help="ISO date, e.g. 2025-12-31")
    p.add_argument("--hold-weeks", type=int, default=8)
    p.add_argument("--max-positions", type=int, default=10)
    p.add_argument("--initial-cash", type=float, default=10_000_000.0)
    p.add_argument("--buy-cost-pct", type=float, default=_BUY_COST_PCT * 100)
    p.add_argument("--sell-cost-pct", type=float, default=_SELL_COST_PCT * 100)
    p.add_argument("--entry-signals", nargs="+", default=None,
                   help=f"default: {' '.join(DEFAULT_ENTRY_SIGNALS)}")
    p.add_argument("--active-exit", action="store_true",
                   help="enable active exit on bearish signals (action_sell, "
                        "pattern_double_top, etc.) — close held positions "
                        "immediately instead of waiting for hold-weeks expiry. "
                        "Book p260-265: 쌍봉/저승사자 = 즉시 청산.")
    p.add_argument("--exit-signals", nargs="+", default=None,
                   help=f"override default exit set: "
                        f"{' '.join(DEFAULT_EXIT_SIGNALS)}")
    p.add_argument("--fires-csv", default=None,
                   help="load pre-computed fires CSV (from sweep --csv), "
                        "skipping the ~14-min walk")
    p.add_argument("--csv", default=None, help="dump per-trade CSV")
    p.add_argument("--regime-filter", action="store_true",
                   help="enable simple KOSPI 월봉 10MA regime filter — "
                        "disable BUY when KOSPI below 10MA (book p318: "
                        "거시 → 추세 → 패턴 우선순위)")
    p.add_argument("--regime-smart", action="store_true",
                   help="enable smart regime filter — block BUY only when "
                        "KOSPI is ≥3%% below 10MA AND MA itself is falling. "
                        "Avoids false-bear blocks during shallow pullbacks.")
    p.add_argument("--regime-threshold-pct", type=float, default=3.0,
                   help="smart filter: %% below 10MA required to consider "
                        "bearish (default: 3.0)")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    # Universe
    if args.tickers:
        universe = list(args.tickers)
    else:
        markets = [args.market] if args.market else ["KOSPI", "KOSDAQ"]
        universe = _list_tickers(markets=markets, limit=args.limit)
        if args.sample:
            import random
            random.seed(args.sample_seed)
            universe = random.sample(universe, min(args.sample, len(universe)))
            universe.sort()

    start_d = date.fromisoformat(args.start)
    end_d = date.fromisoformat(args.end)
    entry_signals = args.entry_signals or list(DEFAULT_ENTRY_SIGNALS)

    log.info("portfolio backtest: %d ticker(s), %s → %s, hold %dw, max_pos %d",
             len(universe), start_d, end_d, args.hold_weeks, args.max_positions)
    log.info("entry signals: %s", ", ".join(entry_signals))

    if args.fires_csv:
        all_fires = load_fires_csv(Path(args.fires_csv))
        log.info("loaded %d fires from %s (skipped walk)",
                 len(all_fires), args.fires_csv)
    else:
        all_fires = collect_universe_fires(universe, args.hold_weeks)
    candidates = filter_entry_fires(all_fires, entry_signals)
    log.info("collected %d fires, %d entry candidates after filter+dedup",
             len(all_fires), len(candidates))

    regime_filter = None
    if args.regime_smart:
        from app.backtest.market_regime import kospi_smart_filter
        regime_filter = kospi_smart_filter(
            below_threshold_pct=args.regime_threshold_pct,
            require_falling_ma=True,
        )
        log.info("regime filter ON (SMART): block only when KOSPI ≥%.1f%% "
                 "below 10MA AND MA falling", args.regime_threshold_pct)
    elif args.regime_filter:
        from app.backtest.market_regime import kospi_regime_filter, regime_stats
        regime_filter = kospi_regime_filter()
        rs = regime_stats()
        log.info("regime filter ON (SIMPLE): KOSPI 월봉 10MA — %d above / "
                 "%d below (%.1f%% bullish months)",
                 rs["n_months_above_10ma"], rs["n_months_below_10ma"],
                 rs["pct_above"] * 100)

    exit_fires_list = None
    if args.active_exit:
        exit_signals = args.exit_signals or list(DEFAULT_EXIT_SIGNALS)
        exit_fires_list = filter_exit_fires(all_fires, exit_signals)
        log.info("active exit ON: %d bearish fires (%s)",
                 len(exit_fires_list), ", ".join(exit_signals))

    state = simulate(
        candidates,
        start_date=start_d, end_date=end_d,
        initial_cash=args.initial_cash,
        max_positions=args.max_positions,
        buy_cost_pct=args.buy_cost_pct / 100.0,
        sell_cost_pct=args.sell_cost_pct / 100.0,
        regime_filter=regime_filter,
        exit_fires=exit_fires_list,
    )

    stats = summarize(state)
    _print_summary(stats)

    if args.csv:
        _save_trades_csv(state, Path(args.csv))
        log.info("trades written to %s", args.csv)

    return 0


if __name__ == "__main__":
    sys.exit(main())
