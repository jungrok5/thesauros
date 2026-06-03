"""Apply v1.1 spec (책 신호 + 책 매도룰) to AMQS universe (19 US AI infra)
over the same 2024-01-02 ~ 2026-05-30 window. Compare to:
 - AMQS reported: CAGR +50.9 / Sharpe 1.46 / MDD -26.6
 - AI-Infra equal-weight buy-and-hold: CAGR +96.2 / Sharpe 2.01
 - QQQ: +28.5
"""
from __future__ import annotations
import csv, sys, time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

import duckdb
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.book.analyzer import analyze_ticker
from app.db.scan_daily import extract_signals
from app.backtest import portfolio as P
from app.backtest.metrics import compute_full_metrics
from app.backtest.portfolio_book import simulate_book_faithful, reset_caches


AMQS_UNIVERSE = [
    "NVDA", "AMD", "INTC", "AVGO", "MRVL", "TSM",
    "MU", "STX", "WDC", "PSTG",
    "DELL", "SMCI", "HPE",
    "ANET", "CSCO",
    "SNOW", "ORCL", "PLTR",
    "VRT",
]

# Sector mapping for sector_cap (use AMQS sub-themes)
US_SECTOR = {
    "NVDA": "GPU", "AMD": "GPU", "INTC": "GPU", "AVGO": "GPU",
    "MRVL": "GPU", "TSM": "GPU",
    "MU": "Memory", "STX": "Memory", "WDC": "Memory", "PSTG": "Memory",
    "DELL": "Server", "SMCI": "Server", "HPE": "Server",
    "ANET": "Network", "CSCO": "Network",
    "SNOW": "DataSW", "ORCL": "DataSW", "PLTR": "DataSW",
    "VRT": "Power",
}


def load_weekly_us(ticker: str) -> pd.DataFrame:
    """Load weekly bars for one US ticker from us_leadlag.duckdb."""
    con = duckdb.connect(str(ROOT / "data" / "us_leadlag.duckdb"),
                         read_only=True)
    rows = con.sql(
        "SELECT bar_date, open, high, low, close, volume FROM bars "
        "WHERE ticker = ? AND granularity='W' ORDER BY bar_date",
        params=[ticker],
    ).fetchall()
    con.close()
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df


def collect_us_fires(ticker: str, hold_weeks: int = 24) -> List[Dict[str, Any]]:
    """Walk all weekly bars, run analyzer at each, record fires."""
    from app.book._swings import clear_swings_cache
    clear_swings_cache()
    df = load_weekly_us(ticker)
    if df.empty or len(df) < 60:
        return []
    out: List[Dict[str, Any]] = []
    last_eligible = len(df) - hold_weeks - 1
    if last_eligible < 60:
        last_eligible = len(df) - 1
    for i in range(60, last_eligible + 1):
        bar_dt = df.iloc[i]["date"].date()
        pit_df = df.iloc[: i + 1].copy()
        pit_df.attrs["grain"] = "W"
        try:
            result = analyze_ticker(ticker, pit_df, weekly=True, monthly=False)
        except Exception:
            continue
        sigs = extract_signals(result)
        if not sigs:
            continue
        entry_price = float(df.iloc[i]["close"])
        if entry_price <= 0: continue
        exit_i = min(i + hold_weeks, len(df) - 1)
        exit_price = float(df.iloc[exit_i]["close"])
        for s in sigs:
            sig = s.get("signal_type", "?")
            tf = s.get("timeframe", "")
            params_dir = s.get("params", {}).get("direction", "")
            from app.backtest.sweep import signal_direction
            direction = signal_direction(sig, params_dir)
            out.append({
                "ticker": ticker, "signal_type": sig, "direction": direction,
                "timeframe": tf, "strength": float(s.get("strength", 0.0)),
                "entry_date": bar_dt.isoformat(), "entry_price": entry_price,
                "exit_date": df.iloc[exit_i]["date"].date().isoformat(),
                "exit_price": exit_price,
                "return_pct": (exit_price/entry_price - 1)*100,
                "effective_return_pct": (exit_price/entry_price - 1)*100,
                "hold_weeks": hold_weeks,
            })
    return out


def main() -> int:
    start = date(2024, 1, 2)
    end = date(2026, 5, 30)
    print(f"window: {start} → {end}")
    print(f"universe: {len(AMQS_UNIVERSE)} US AI infra tickers\n")

    print("collecting fires from analyze_ticker ...")
    all_fires: List[Dict[str, Any]] = []
    for tic in AMQS_UNIVERSE:
        fires = collect_us_fires(tic)
        print(f"  {tic}: {len(fires)} fires")
        all_fires.extend(fires)
    print(f"\ntotal fires: {len(all_fires):,}")

    fires_buy = P.filter_entry_fires(all_fires, P.DEFAULT_ENTRY_SIGNALS)
    exit_fires = [
        f for f in all_fires
        if f.get("signal_type") in P.DEFAULT_EXIT_SIGNALS
        and f.get("timeframe") == "weekly"
    ]
    print(f"buy fires (5 entry signals): {len(fires_buy):,}")
    print(f"exit fires (천장 patterns): {len(exit_fires):,}")

    # Filter to window
    fires_window = [f for f in fires_buy
                    if start.isoformat() <= f["entry_date"] <= end.isoformat()]
    exit_window = [f for f in exit_fires
                   if start.isoformat() <= f["entry_date"] <= end.isoformat()]
    print(f"in window: {len(fires_window):,} buy / {len(exit_window):,} exit")

    # Apply sector_cap with AMQS sub-themes
    from collections import defaultdict
    from scripts.grid_phase5_factors import week_bucket
    by_week = defaultdict(list)
    for f in fires_window:
        by_week[week_bucket(f["entry_date"])].append(f)
    capped = []
    for wk, items in by_week.items():
        items.sort(key=lambda x: float(x.get("strength", 0)), reverse=True)
        kept = defaultdict(int)
        for it in items:
            sec = US_SECTOR.get(it["ticker"], "_UNK")
            if kept[sec] >= 1: continue
            kept[sec] += 1
            capped.append(it)
    print(f"after sector_cap=1: {len(capped):,} cands")

    # Monkey-patch local_store to use us_leadlag.duckdb for this run
    from app.backtest import local_store
    orig_path = local_store.DEFAULT_DB_PATH
    local_store.DEFAULT_DB_PATH = ROOT / "data" / "us_leadlag.duckdb"
    try:
        reset_caches()
        state = simulate_book_faithful(
            capped, start, end,
            initial_cash=100_000_000.0, max_positions=10,
            exit_fires=exit_window, delisting_dates=None,
        )
    finally:
        local_store.DEFAULT_DB_PATH = orig_path

    # Compute metrics — but compute_full_metrics uses ^KS11 (KR KOSPI).
    # For US comparison we need our own simple CAGR/Sharpe.
    eq_history = state.equity_history
    if not eq_history:
        print("\nno trades / no equity history")
        return 0
    eq_df = pd.DataFrame(eq_history, columns=["date", "equity"])
    eq_df["date"] = pd.to_datetime(eq_df["date"])
    eq_df = eq_df.set_index("date").resample("W-FRI").last().dropna()
    initial = float(eq_df["equity"].iloc[0])
    final = float(eq_df["equity"].iloc[-1])
    weeks = len(eq_df)
    years = weeks / 52
    cagr = (final / initial) ** (1/years) - 1 if initial > 0 else 0
    rets = eq_df["equity"].pct_change().dropna()
    sharpe = rets.mean() / rets.std() * (52 ** 0.5) if rets.std() else 0
    peak = eq_df["equity"].cummax()
    dd = (eq_df["equity"] / peak - 1).min()

    print(f"\n── v1.1 spec on AMQS universe ({weeks} weeks / {years:.2f} years) ──")
    print(f"  initial: {initial:,.0f}")
    print(f"  final:   {final:,.0f}")
    print(f"  total return: {(final/initial - 1)*100:+.1f}%")
    print(f"  CAGR:    {cagr*100:+.2f}%")
    print(f"  Sharpe:  {sharpe:+.2f}")
    print(f"  MDD:     {dd*100:+.2f}%")
    print(f"  n_trades: {len(state.trades)}")

    # Equal-weight benchmark
    print("\n── benchmarks (same window) ──")
    import yfinance as yf
    for bench in ["QQQ", "SMH", "^GSPC"]:
        try:
            b = yf.download(bench, start=start.isoformat(),
                            end=end.isoformat(), progress=False, auto_adjust=False)
            if isinstance(b.columns, pd.MultiIndex):
                b.columns = b.columns.get_level_values(0)
            init = float(b["Close"].iloc[0])
            fin = float(b["Close"].iloc[-1])
            print(f"  {bench}: total {(fin/init - 1)*100:+.1f}%  CAGR {((fin/init)**(1/years) - 1)*100:+.2f}%")
        except Exception as e:
            print(f"  {bench}: ERROR {e}")

    # 19-ticker equal-weight backtest
    print("\nEqual-weight 19-ticker buy-and-hold:")
    eq_curves = []
    for tic in AMQS_UNIVERSE:
        df = load_weekly_us(tic)
        if df.empty: continue
        df = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]
        if len(df) < 2: continue
        df = df.set_index("date")
        df["norm"] = df["close"] / df["close"].iloc[0]
        eq_curves.append(df["norm"].rename(tic))
    if eq_curves:
        merged = pd.concat(eq_curves, axis=1).ffill()
        ew = merged.mean(axis=1)
        ew_total = float(ew.iloc[-1]) - 1
        ew_cagr = (float(ew.iloc[-1])) ** (1/years) - 1
        rets_ew = ew.pct_change().dropna()
        sh_ew = rets_ew.mean() / rets_ew.std() * (52 ** 0.5) if rets_ew.std() else 0
        peak_ew = ew.cummax()
        dd_ew = (ew / peak_ew - 1).min()
        print(f"  total:  {ew_total*100:+.1f}%")
        print(f"  CAGR:   {ew_cagr*100:+.2f}%")
        print(f"  Sharpe: {sh_ew:+.2f}")
        print(f"  MDD:    {dd_ew*100:+.2f}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())
