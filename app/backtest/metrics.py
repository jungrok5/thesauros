"""Risk-adjusted metrics for portfolio backtest results.

Phase 4 portfolio.summarize() reports trade-based metrics (win_rate,
payoff, max_drawdown_from_event_history). Those are biased optimistic
because equity is "frozen" between cash-flow events — actual unrealised
P&L on held positions is hidden, undervaluing volatility → overstating
Sharpe-like measures.

This module computes the proper mark-to-market (MTM) weekly equity
time series and the risk-adjusted ratios:

  - Sharpe ratio (annualised, vs risk-free)
  - Sortino ratio (downside-only Sharpe)
  - Calmar ratio (annualised return / max DD)
  - alpha + beta vs KOSPI BH (CAPM-style OLS)
  - max drawdown (from MTM, more honest than event-based)

Usage:
    from app.backtest.metrics import compute_full_metrics
    metrics = compute_full_metrics(state, start, end)
    # → {sharpe, sortino, calmar, alpha_annual, beta, r2,
    #     max_dd_mtm, n_weeks, ...}
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

log = logging.getLogger("backtest.metrics")

# Korean Treasury 10y ~3-4% in recent years. Use 3.0% as a conservative
# constant rf for Sharpe denominators. Override via compute_full_metrics
# arg if user wants period-specific.
RISK_FREE_ANNUAL_DEFAULT = 0.03

# Annualisation factor for WEEKLY returns: 52 weeks. (Some literature
# uses 50 or 52 — we use 52 because our W-FRI bars are weekly.)
WEEKS_PER_YEAR = 52


# ─────────────────────────────────────────────────────────────────────
# Weekly MTM equity series
# ─────────────────────────────────────────────────────────────────────

def weekly_equity_series(
    state, start_date: date, end_date: date,
    get_close_fn=None,
) -> pd.DataFrame:
    """Build week-by-week mark-to-market equity time series.

    For each Friday in [start, end]:
        equity = cash (after all cash flows up to that Friday)
               + sum(shares × close at that Friday for held positions)

    `get_close_fn(ticker, date) → float | None`: price lookup. Defaults
    to load_bars-based weekly close (cached locally).

    Returns DataFrame: date | cash | mtm_holdings | equity | weekly_return.
    """
    if get_close_fn is None:
        get_close_fn = _default_get_close

    initial_cash = state.initial_cash
    trades = state.trades

    # Build cash-flow + position-change events from trades.
    events: List[Tuple[date, str, float, str, float]] = []
    for t in trades:
        # Buy event: cash leaves, shares acquired.
        events.append((t.entry_date, "buy", -t.cost_basis_krw,
                       t.ticker, t.shares))
        # Sell event: cash returns (post-fee proceeds), shares released.
        events.append((t.exit_date, "sell", +t.proceeds_krw,
                       t.ticker, 0.0))
    events.sort(key=lambda e: (e[0], 0 if e[1] == "sell" else 1))

    # Walk weekly Fridays. At each Friday, apply all events up to & inc.
    fridays = pd.date_range(
        pd.Timestamp(start_date), pd.Timestamp(end_date), freq="W-FRI",
    )
    if len(fridays) == 0:
        return pd.DataFrame(columns=["date", "cash", "mtm_holdings",
                                     "equity", "weekly_return"])

    cash = initial_cash
    open_positions: Dict[str, float] = {}   # ticker → shares
    event_idx = 0
    rows: List[Dict[str, Any]] = []
    for fri in fridays:
        fri_date = fri.date()
        while event_idx < len(events) and events[event_idx][0] <= fri_date:
            ev_date, kind, cash_delta, ticker, shares = events[event_idx]
            cash += cash_delta
            if kind == "buy":
                open_positions[ticker] = open_positions.get(ticker, 0) + shares
            else:  # sell
                if ticker in open_positions:
                    del open_positions[ticker]
            event_idx += 1
        # MTM open positions
        mtm_holdings = 0.0
        for tk, shr in open_positions.items():
            close = get_close_fn(tk, fri_date)
            if close is not None and close > 0:
                mtm_holdings += shr * close
        equity = cash + mtm_holdings
        rows.append({
            "date": fri_date,
            "cash": cash,
            "mtm_holdings": mtm_holdings,
            "equity": equity,
        })

    df = pd.DataFrame(rows)
    df["weekly_return"] = df["equity"].pct_change()
    return df


_BARS_CACHE: Dict[str, "pd.DataFrame"] = {}


def _cached_bars_W(ticker: str):
    """One DuckDB roundtrip per ticker per process. Comment in the
    pre-2026-05-29 implementation claimed lru_cache; there was none
    — each weekly_equity_series call hit DuckDB ~45k times for a
    50-position 17-year run, taking 10-30+ minutes."""
    df = _BARS_CACHE.get(ticker)
    if df is None:
        from app.backtest.local_store import load_bars
        df = load_bars(ticker, "W")
        _BARS_CACHE[ticker] = df
    return df


def _default_get_close(ticker: str, on_date: date) -> Optional[float]:
    """Lookup ticker's last weekly close ≤ on_date. DuckDB load is
    cached per-process via _BARS_CACHE."""
    df = _cached_bars_W(ticker)
    if df.empty:
        return None
    mask = df["date"].dt.date <= on_date
    if not mask.any():
        return None
    return float(df.loc[mask].iloc[-1]["close"])


# ─────────────────────────────────────────────────────────────────────
# Risk-adjusted ratios
# ─────────────────────────────────────────────────────────────────────

def sharpe_ratio(
    equity_df: pd.DataFrame, risk_free_annual: float = RISK_FREE_ANNUAL_DEFAULT,
) -> Optional[float]:
    """Annualised Sharpe ratio from weekly equity.

    Sharpe = (annualised_return - risk_free) / annualised_vol.
    Standard convention: mean and std of weekly excess returns,
    multiplied by sqrt(52) for annualisation.

    Returns None if < 10 valid weekly returns (too few for meaningful
    statistic) or zero variance.
    """
    rets = equity_df["weekly_return"].dropna()
    if len(rets) < 10:
        return None
    rf_weekly = risk_free_annual / WEEKS_PER_YEAR
    excess = rets - rf_weekly
    std_weekly = excess.std()
    # Use small epsilon — pct_change of constant series gives 0.0 exact
    # but excess deduction + float precision can leave a sub-pico residue.
    if std_weekly is None or std_weekly < 1e-12:
        return None
    return float(excess.mean() / std_weekly * math.sqrt(WEEKS_PER_YEAR))


def sortino_ratio(
    equity_df: pd.DataFrame, risk_free_annual: float = RISK_FREE_ANNUAL_DEFAULT,
) -> Optional[float]:
    """Sortino — Sharpe but uses downside-only deviation. Less penalty
    for upside volatility. More relevant for asymmetric strategies."""
    rets = equity_df["weekly_return"].dropna()
    if len(rets) < 10:
        return None
    rf_weekly = risk_free_annual / WEEKS_PER_YEAR
    excess = rets - rf_weekly
    downside = excess[excess < 0]
    if len(downside) < 5:
        return None
    ds_std = downside.std()
    if ds_std is None or ds_std < 1e-12:
        return None
    return float(excess.mean() / ds_std * math.sqrt(WEEKS_PER_YEAR))


def calmar_ratio(equity_df: pd.DataFrame) -> Optional[float]:
    """Calmar = annualised_return / max_drawdown_pct. Higher = recovery
    from drawdowns happens faster relative to size of drawdowns.
    Robust to short backtest periods (no std dependency)."""
    if len(equity_df) < 2:
        return None
    initial = equity_df["equity"].iloc[0]
    final = equity_df["equity"].iloc[-1]
    if initial <= 0:
        return None
    n_weeks = len(equity_df) - 1
    if n_weeks < WEEKS_PER_YEAR:
        return None     # need at least 1 full year
    annualised = (final / initial) ** (WEEKS_PER_YEAR / n_weeks) - 1
    max_dd = max_drawdown_pct(equity_df)
    if max_dd is None or max_dd == 0:
        return None
    return float(annualised / max_dd)


def max_drawdown_pct(equity_df: pd.DataFrame) -> Optional[float]:
    """Max peak-to-trough drawdown as a positive % (0.43 = 43% DD).
    Computed on the full MTM time series so it captures intra-trade
    volatility, NOT just event-time low points."""
    if equity_df.empty:
        return None
    eq = equity_df["equity"]
    peak = eq.cummax()
    dd = (peak - eq) / peak
    return float(dd.max()) if dd.notna().any() else None


def annualised_return(equity_df: pd.DataFrame) -> Optional[float]:
    """Compound annualised return from the weekly equity."""
    if len(equity_df) < 2:
        return None
    initial = equity_df["equity"].iloc[0]
    final = equity_df["equity"].iloc[-1]
    if initial <= 0:
        return None
    n_weeks = len(equity_df) - 1
    if n_weeks == 0:
        return None
    return float((final / initial) ** (WEEKS_PER_YEAR / n_weeks) - 1)


# ─────────────────────────────────────────────────────────────────────
# Alpha + beta vs KOSPI buy-and-hold
# ─────────────────────────────────────────────────────────────────────

def alpha_beta_vs_kospi(
    equity_df: pd.DataFrame,
    risk_free_annual: float = RISK_FREE_ANNUAL_DEFAULT,
) -> Optional[Dict[str, float]]:
    """OLS regression of portfolio weekly excess return vs KOSPI weekly
    excess return.

        r_portfolio - rf = alpha + beta * (r_kospi - rf) + epsilon

    Returns:
        alpha_weekly       — weekly excess alpha (intercept)
        alpha_annual       — annualised alpha (alpha_weekly * 52)
        beta               — slope (market sensitivity)
        r_squared          — fit quality
        n_weeks            — sample size
        portfolio_ann_ret  — annualised portfolio return (for context)
        kospi_ann_ret      — annualised KOSPI return (same period)

    Returns None if KOSPI bars unavailable or < 10 aligned weeks.
    """
    from app.backtest.local_store import load_bars
    kospi = load_bars("^KS11", "W")
    if kospi.empty:
        log.warning("KOSPI bars not in local store — alpha/beta unavailable")
        return None

    portfolio = equity_df[["date", "equity"]].copy()
    portfolio["date"] = pd.to_datetime(portfolio["date"])
    kospi = kospi[["date", "close"]].copy()
    kospi["date"] = pd.to_datetime(kospi["date"])
    merged = portfolio.merge(kospi, on="date", how="inner", suffixes=("", "_k"))
    if len(merged) < 10:
        return None
    merged["r_p"] = merged["equity"].pct_change()
    merged["r_k"] = merged["close"].pct_change()
    merged = merged.dropna(subset=["r_p", "r_k"])
    if len(merged) < 10:
        return None

    rf_weekly = risk_free_annual / WEEKS_PER_YEAR
    x = (merged["r_k"] - rf_weekly).values
    y = (merged["r_p"] - rf_weekly).values

    # OLS: y = alpha + beta * x
    x_mean, y_mean = x.mean(), y.mean()
    var_x = ((x - x_mean) ** 2).sum()
    if var_x == 0:
        return None
    cov_xy = ((x - x_mean) * (y - y_mean)).sum()
    beta = cov_xy / var_x
    alpha = y_mean - beta * x_mean

    # R²
    y_pred = alpha + beta * x
    ss_res = ((y - y_pred) ** 2).sum()
    ss_tot = ((y - y_mean) ** 2).sum()
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Annualised returns for context
    n_weeks = len(merged)
    port_total = merged["equity"].iloc[-1] / merged["equity"].iloc[0]
    kospi_total = merged["close"].iloc[-1] / merged["close"].iloc[0]
    port_ann = port_total ** (WEEKS_PER_YEAR / n_weeks) - 1
    kospi_ann = kospi_total ** (WEEKS_PER_YEAR / n_weeks) - 1

    return {
        "alpha_weekly": float(alpha),
        "alpha_annual": float(alpha * WEEKS_PER_YEAR),
        "beta": float(beta),
        "r_squared": float(r_squared),
        "n_weeks": int(n_weeks),
        "portfolio_ann_ret": float(port_ann),
        "kospi_ann_ret": float(kospi_ann),
    }


# ─────────────────────────────────────────────────────────────────────
# Wrap-up: compute everything from a PortfolioState
# ─────────────────────────────────────────────────────────────────────

def compute_full_metrics(
    state, start_date: date, end_date: date,
    risk_free_annual: float = RISK_FREE_ANNUAL_DEFAULT,
) -> Dict[str, Any]:
    """Compute the full set of risk-adjusted metrics + alpha/beta.

    Returns flat dict. Missing values keyed as None.
    """
    eq = weekly_equity_series(state, start_date, end_date)
    if eq.empty:
        return {"error": "empty equity series"}
    out: Dict[str, Any] = {
        "n_weeks": len(eq),
        "initial_equity": float(eq["equity"].iloc[0]),
        "final_equity": float(eq["equity"].iloc[-1]),
        "total_return_pct": float(
            eq["equity"].iloc[-1] / eq["equity"].iloc[0] - 1
        ) * 100.0,
        "annualised_return_pct": (annualised_return(eq) or 0) * 100.0,
        "max_drawdown_mtm_pct": (max_drawdown_pct(eq) or 0) * 100.0,
        "sharpe": sharpe_ratio(eq, risk_free_annual),
        "sortino": sortino_ratio(eq, risk_free_annual),
        "calmar": calmar_ratio(eq),
    }
    ab = alpha_beta_vs_kospi(eq, risk_free_annual)
    if ab is not None:
        out.update({
            "alpha_annual_pct": ab["alpha_annual"] * 100.0,
            "beta": ab["beta"],
            "r_squared": ab["r_squared"],
            "kospi_ann_ret_pct": ab["kospi_ann_ret"] * 100.0,
            # outperformance vs KOSPI BH
            "outperformance_ann_pct": (
                (annualised_return(eq) or 0) - ab["kospi_ann_ret"]
            ) * 100.0,
        })
    out["_equity_df"] = eq      # caller can dump if they want
    return out


def print_metrics(metrics: Dict[str, Any]) -> None:
    """Pretty-print metrics summary."""
    print()
    print("=" * 70)
    print("RISK-ADJUSTED METRICS")
    print("=" * 70)
    fmt = {
        "n_weeks": "{:>10d}",
        "initial_equity": "{:>14,.0f}",
        "final_equity": "{:>14,.0f}",
        "total_return_pct": "{:>+10.2f}%",
        "annualised_return_pct": "{:>+10.2f}%",
        "max_drawdown_mtm_pct": "{:>10.2f}%",
        "sharpe": "{:>10.3f}",
        "sortino": "{:>10.3f}",
        "calmar": "{:>10.3f}",
        "alpha_annual_pct": "{:>+10.2f}%",
        "beta": "{:>10.3f}",
        "r_squared": "{:>10.3f}",
        "kospi_ann_ret_pct": "{:>+10.2f}%",
        "outperformance_ann_pct": "{:>+10.2f}%",
    }
    for k, fstr in fmt.items():
        v = metrics.get(k)
        if v is None:
            print(f"  {k:30s}        n/a")
        else:
            print(f"  {k:30s} {fstr.format(v)}")
    print("=" * 70)
