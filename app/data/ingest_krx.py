"""Ingest Korean stock prices via FinanceDataReader (was pykrx).

FDR is used for the *universe listing* because pykrx hit a Windows-CP949
encoding bug on this machine. The actual OHLCV fetch still uses pykrx
(it works fine for `get_market_ohlcv` by single ticker) — falling back
to FDR if pykrx fails.

Tickers follow the `<6-digit>.<KS|KQ>` convention so they sit alongside
US tickers in the same `prices` table.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional

import pandas as pd

from app.data.pit_db import connect, cursor


def krx_universe(market: str = "ALL") -> List[Dict]:
    """List all KOSPI/KOSDAQ tickers via FinanceDataReader.

    Returns dicts: {ticker (5930.KS form), code (6-digit), name, market}
    """
    import FinanceDataReader as fdr
    listing = fdr.StockListing("KRX")

    universe = []
    for _, row in listing.iterrows():
        code = str(row.get("Code", "")).strip()
        if not code or not code.isdigit() or len(code) != 6:
            continue
        market_id = row.get("MarketId") or row.get("Market") or ""
        # MarketId: STK=KOSPI, KSQ=KOSDAQ, KNX=KONEX
        if "STK" in str(market_id) or str(row.get("Market", "")).upper() == "KOSPI":
            suffix, m_name = ".KS", "KOSPI"
        elif "KSQ" in str(market_id) or str(row.get("Market", "")).upper() == "KOSDAQ":
            suffix, m_name = ".KQ", "KOSDAQ"
        else:
            continue
        if market != "ALL" and m_name != market:
            continue
        name = row.get("Name", "") or row.get("종목명", "")
        universe.append({
            "ticker": f"{code}{suffix}",
            "code": code,
            "name": name,
            "market": m_name,
        })
    return universe


def _fetch_pykrx(code: str, start: str, end: str) -> pd.DataFrame:
    """Try pykrx (Korean column headers). Returns empty df on failure."""
    try:
        from pykrx import stock as krx
        df = krx.get_market_ohlcv(start, end, code)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.reset_index()
    # pykrx columns may be Korean or mangled CP949. Try both.
    col_map = {
        "날짜": "date", "시가": "open", "고가": "high",
        "저가": "low", "종가": "close", "거래량": "volume",
    }
    df = df.rename(columns=col_map)
    # If still no "open" / "close", fall through to FDR
    if "close" not in df.columns or "open" not in df.columns:
        return pd.DataFrame()
    return df


def _fetch_fdr(code: str, start: str, end: str) -> pd.DataFrame:
    """FinanceDataReader fallback (English column headers, robust)."""
    import FinanceDataReader as fdr
    s = pd.to_datetime(start, format="%Y%m%d").strftime("%Y-%m-%d")
    e = pd.to_datetime(end, format="%Y%m%d").strftime("%Y-%m-%d")
    try:
        df = fdr.DataReader(code, s, e)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.reset_index().rename(columns={
        "Date": "date", "Open": "open", "High": "high",
        "Low": "low", "Close": "close", "Volume": "volume",
    })
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.date
    return df


def _fetch_one(code: str, suffix: str, start: str, end: str) -> pd.DataFrame:
    df = _fetch_pykrx(code, start, end)
    if df.empty:
        df = _fetch_fdr(code, start, end)
    if df.empty:
        return df
    if "date" not in df.columns:
        return pd.DataFrame()
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
        try:
            top = ", ".join(
                f"{k}={v}" for k, v in
                sorted(counts.items(), key=lambda x: -x[1])[:5]
            )
            print(f"[krx] done. top counts: {top}")
        except UnicodeEncodeError:
            print("[krx] done.")
    return counts


def ingest_kospi200_kosdaq150(years: int = 5, workers: int = 4, verbose: bool = True
                              ) -> Dict[str, int]:
    """Convenience: large-cap KOSPI + mid-cap KOSDAQ subset (top by mcap).

    pykrx index endpoints are unreliable on Windows due to CP949 issues, so
    we use FDR's StockListing + filter top-N by market cap.
    """
    import FinanceDataReader as fdr
    listing = fdr.StockListing("KRX")
    listing = listing[listing["Code"].astype(str).str.match(r"^\d{6}$", na=False)]
    listing["Marcap"] = pd.to_numeric(listing.get("Marcap"), errors="coerce")
    listing = listing.dropna(subset=["Marcap"])

    universe = []
    # Top 200 KOSPI (STK) by mcap
    kospi = listing[listing.get("MarketId", "") == "STK"].nlargest(200, "Marcap")
    for _, r in kospi.iterrows():
        universe.append({
            "ticker": f"{r['Code']}.KS", "code": r["Code"], "market": "KOSPI",
        })
    # Top 150 KOSDAQ (KSQ) by mcap
    kosdaq = listing[listing.get("MarketId", "") == "KSQ"].nlargest(150, "Marcap")
    for _, r in kosdaq.iterrows():
        universe.append({
            "ticker": f"{r['Code']}.KQ", "code": r["Code"], "market": "KOSDAQ",
        })
    return ingest(universe, years=years, workers=workers, verbose=verbose)
