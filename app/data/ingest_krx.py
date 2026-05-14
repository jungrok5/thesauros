"""Ingest Korean stock prices via pykrx.

Tickers follow the same `<6-digit>.<KS|KQ>` convention as yfinance, so they
fit into the existing `prices` table alongside US data.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional

import pandas as pd

from app.data.pit_db import connect, cursor


def krx_universe(market: str = "ALL") -> List[Dict]:
    """List all KOSPI and/or KOSDAQ tickers via pykrx.

    Returns dicts: {ticker (5930.KS form), code (6-digit), name, market}
    """
    from pykrx import stock as krx
    today = datetime.today().strftime("%Y%m%d")

    universe = []
    targets = ["KOSPI", "KOSDAQ"] if market == "ALL" else [market]
    for m in targets:
        codes = krx.get_market_ticker_list(today, market=m)
        for code in codes:
            name = krx.get_market_ticker_name(code)
            suffix = ".KS" if m == "KOSPI" else ".KQ"
            universe.append({
                "ticker": f"{code}{suffix}",
                "code": code,
                "name": name,
                "market": m,
            })
    return universe


def _fetch_one(code: str, suffix: str, start: str, end: str) -> pd.DataFrame:
    from pykrx import stock as krx
    try:
        df = krx.get_market_ohlcv(start, end, code)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.reset_index().rename(columns={
        "날짜": "date", "시가": "open", "고가": "high",
        "저가": "low", "종가": "close", "거래량": "volume",
    })
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["ticker"] = f"{code}{suffix}"
    df["adj_close"] = df["close"]  # pykrx already returns adjusted
    return df[["ticker", "date", "open", "high", "low", "close", "adj_close", "volume"]]


def _last_dates() -> Dict[str, date]:
    with cursor() as con:
        df = con.execute(
            "SELECT ticker, MAX(date) AS d FROM prices "
            "WHERE ticker LIKE '%.KS' OR ticker LIKE '%.KQ' "
            "GROUP BY ticker"
        ).df()
    return {r["ticker"]: r["d"] for _, r in df.iterrows() if pd.notna(r["d"])}


def ingest(tickers: Iterable[Dict], years: int = 5,
           workers: int = 4, verbose: bool = True) -> Dict[str, int]:
    """Bulk-fetch KRX OHLCV. tickers = list of {ticker, code, market} dicts."""
    tickers = list(tickers)
    last_dates = _last_dates()
    counts: Dict[str, int] = {}
    frames: List[pd.DataFrame] = []
    end = datetime.today().strftime("%Y%m%d")

    def _start_for(t: str) -> str:
        ld = last_dates.get(t)
        if ld is not None:
            return (ld + timedelta(days=1)).strftime("%Y%m%d")
        return (date.today() - timedelta(days=years * 365 + 30)).strftime("%Y%m%d")

    def _job(t: Dict) -> tuple[str, pd.DataFrame]:
        start = _start_for(t["ticker"])
        if start >= end:
            return t["ticker"], pd.DataFrame()
        suffix = ".KS" if t["market"] == "KOSPI" else ".KQ"
        df = _fetch_one(t["code"], suffix, start, end)
        return t["ticker"], df

    if verbose:
        print(f"[krx] fetching {len(tickers)} tickers (workers={workers})...")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_job, t): t["ticker"] for t in tickers}
        for fut in as_completed(futs):
            ticker = futs[fut]
            try:
                _, df = fut.result()
            except Exception as e:
                if verbose:
                    print(f"  [{ticker}] error: {e}")
                df = pd.DataFrame()
            counts[ticker] = len(df)
            if not df.empty:
                frames.append(df)

    if not frames:
        return counts

    big = pd.concat(frames, ignore_index=True)
    big = big.dropna(subset=["date", "ticker"])

    if verbose:
        print(f"[krx] fetched {len(big):,} rows; bulk inserting...")
    con = connect()
    try:
        con.register("df_in", big)
        con.execute("""
            INSERT OR REPLACE INTO prices
            (ticker, date, open, high, low, close, adj_close, volume)
            SELECT ticker, date, open, high, low, close, adj_close, volume FROM df_in
        """)
    finally:
        con.close()

    if verbose:
        print(f"[krx] done — top counts: " + ", ".join(
            f"{k}={v}" for k, v in sorted(counts.items(), key=lambda x: -x[1])[:5]
        ))
    return counts


def ingest_kospi200_kosdaq150(years: int = 5, workers: int = 4, verbose: bool = True
                              ) -> Dict[str, int]:
    """Convenience: KOSPI200 + KOSDAQ150 (used as our default KR universe)."""
    from pykrx import stock as krx
    today = datetime.today().strftime("%Y%m%d")
    kospi200_codes = set(krx.get_index_portfolio_deposit_file("1028", today))
    kosdaq150_codes = set(krx.get_index_portfolio_deposit_file("2203", today))

    universe = []
    for code in kospi200_codes:
        universe.append({"ticker": f"{code}.KS", "code": code, "market": "KOSPI"})
    for code in kosdaq150_codes:
        universe.append({"ticker": f"{code}.KQ", "code": code, "market": "KOSDAQ"})
    return ingest(universe, years=years, workers=workers, verbose=verbose)
