"""KR 상장폐지 종목 메타데이터 + 가격 적재 (survivorship bias 보정용).

생성/사용 테이블:
  delisted_tickers (
      ticker VARCHAR PRIMARY KEY,
      name VARCHAR,
      market VARCHAR,          -- KOSPI / KOSDAQ
      listing_date DATE,
      delisting_date DATE,
      reason VARCHAR,
      to_ticker VARCHAR,       -- 합병/분할 후 승계 종목
      to_name VARCHAR
  )

  prices — 기존 테이블, 상폐 종목 가격 같이 적재
            (ticker 충돌 없음. ".KS"/".KQ" suffix 추가)

PIT 안전성:
  백테스트 시점 t 에서 "그 시점에 살아있던 종목만" universe 로 사용.
  → survivorship bias 제거.

  사용법:
      SELECT ticker FROM delisted_tickers
       WHERE delisting_date > '2020-01-01'
      UNION
      SELECT DISTINCT ticker FROM prices
       WHERE date >= '2020-01-01' AND ticker NOT IN (
           SELECT ticker FROM delisted_tickers WHERE delisting_date <= '2020-01-01'
       )
"""
from __future__ import annotations

import sys
import time
from typing import Dict, List, Optional

import pandas as pd

from app.data.pit_db import cursor


def ensure_table() -> None:
    """Create delisted_tickers table if not exists."""
    with cursor() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS delisted_tickers (
                ticker VARCHAR PRIMARY KEY,
                name VARCHAR,
                market VARCHAR,
                listing_date DATE,
                delisting_date DATE,
                reason VARCHAR,
                to_ticker VARCHAR,
                to_name VARCHAR
            )
        """)


def _is_common_stock(symbol: str) -> bool:
    """일반 보통주만 (6자리 숫자). 신주인수권/우선주/REIT 등은 제외."""
    if not symbol or len(symbol) != 6:
        return False
    return symbol.isdigit()


def fetch_delisted_metadata(min_delist_date: str = "2008-01-01",
                             common_only: bool = True) -> pd.DataFrame:
    """FDR 에서 KR 상폐 종목 메타데이터 fetch."""
    import FinanceDataReader as fdr
    df = fdr.StockListing("KRX-DELISTING")
    df["DelistingDate"] = pd.to_datetime(df["DelistingDate"], errors="coerce")
    df["ListingDate"] = pd.to_datetime(df["ListingDate"], errors="coerce")
    df = df[df["DelistingDate"] >= pd.Timestamp(min_delist_date)].copy()
    if common_only:
        df = df[df["Symbol"].apply(_is_common_stock)]
    return df


def ingest_metadata(min_delist_date: str = "2008-01-01",
                    common_only: bool = True,
                    verbose: bool = True) -> int:
    """상폐 종목 메타 적재. ticker = "<symbol>.KS" / "<symbol>.KQ"."""
    ensure_table()
    df = fetch_delisted_metadata(min_delist_date=min_delist_date,
                                  common_only=common_only)
    if df.empty:
        if verbose:
            print("[delisted-kr] no rows.")
        return 0

    # ticker = symbol + ".KS"/".KQ" (matches our prices table format)
    def _ticker(row):
        suffix = ".KS" if row["Market"] == "KOSPI" else ".KQ"
        return f"{row['Symbol']}{suffix}"

    df["ticker_full"] = df.apply(_ticker, axis=1)

    rows = []
    for _, r in df.iterrows():
        rows.append({
            "ticker": r["ticker_full"],
            "name": r.get("Name"),
            "market": r.get("Market"),
            "listing_date": (r["ListingDate"].date()
                              if pd.notna(r["ListingDate"]) else None),
            "delisting_date": (r["DelistingDate"].date()
                                if pd.notna(r["DelistingDate"]) else None),
            "reason": r.get("Reason"),
            "to_ticker": r.get("ToSymbol"),
            "to_name": r.get("ToName"),
        })

    out_df = pd.DataFrame(rows)
    con = None
    try:
        from app.data.pit_db import connect
        con = connect()
        con.register("df_meta", out_df)
        con.execute("""
            INSERT OR REPLACE INTO delisted_tickers
              (ticker, name, market, listing_date, delisting_date,
               reason, to_ticker, to_name)
            SELECT ticker, name, market, listing_date, delisting_date,
                   reason, to_ticker, to_name FROM df_meta
        """)
    finally:
        if con:
            con.close()

    if verbose:
        print(f"[delisted-kr] {len(rows)} metadata rows ingested "
              f"(common stocks only, delisted ≥{min_delist_date})")
    return len(rows)


def ingest_prices(min_delist_date: str = "2008-01-01",
                  verbose: bool = True,
                  max_tickers: Optional[int] = None) -> Dict[str, int]:
    """상폐 종목 가격 적재 (pykrx 시도, 실패 시 skip)."""
    ensure_table()
    with cursor() as con:
        rows = con.execute(
            "SELECT ticker, name, market, delisting_date "
            "FROM delisted_tickers "
            "WHERE delisting_date >= ? ORDER BY delisting_date DESC",
            [min_delist_date],
        ).fetchall()

    if max_tickers:
        rows = rows[:max_tickers]

    if verbose:
        print(f"[delisted-kr] price ingest for {len(rows)} tickers")

    from pykrx import stock as pkx
    counts = {}
    ok = err = no_data = 0
    for i, (tk, name, market, delist) in enumerate(rows, 1):
        symbol = tk.split(".")[0]
        # Listing → delisting full range; KRX limit so fetch in chunks
        start = "20080101"
        end = pd.Timestamp(delist).strftime("%Y%m%d") if delist else "20251231"
        try:
            df = pkx.get_market_ohlcv(start, end, symbol, "d")
            if df is None or df.empty:
                no_data += 1
                continue
            df = df.reset_index()
            # pykrx columns: 날짜, 시가, 고가, 저가, 종가, 거래량
            df.columns = [c.lower() for c in df.columns]
            ren = {"날짜": "date", "시가": "open", "고가": "high",
                   "저가": "low", "종가": "close", "거래량": "volume"}
            df = df.rename(columns={k.lower(): v for k, v in ren.items()})
            df["ticker"] = tk
            df["adj_close"] = df["close"]  # pykrx 는 split-adjusted 가 별도 없음
            # Insert to prices
            from app.data.pit_db import connect
            con2 = connect()
            try:
                con2.register("df_px", df[["ticker", "date", "open", "high",
                                             "low", "close", "adj_close",
                                             "volume"]])
                con2.execute("""
                    INSERT OR IGNORE INTO prices
                      (ticker, date, open, high, low, close, adj_close, volume)
                    SELECT ticker, date, open, high, low, close, adj_close, volume
                    FROM df_px
                """)
            finally:
                con2.close()
            counts[tk] = len(df)
            ok += 1
        except Exception as e:
            err += 1
            if verbose and err <= 5:
                print(f"  [{i}/{len(rows)}] {tk} ERR: {type(e).__name__}: {e}")
        time.sleep(0.05)  # rate limit
        if verbose and i % 50 == 0:
            print(f"  [{i}/{len(rows)}] ok={ok} no_data={no_data} err={err}")

    if verbose:
        print(f"[delisted-kr] DONE. {ok} ingested, {no_data} no-data, {err} errors")
    return counts


def universe_alive_at(date_str: str,
                       market: Optional[str] = None) -> List[str]:
    """`date_str` 시점에 살아있던 종목 리스트 (survivorship-bias-safe).

    Args:
        date_str: ISO date
        market: 'kr' (.KS/.KQ), 'us' (no suffix), None (all)

    Returns: list of tickers.

    🚨 IMPORTANT (Bug #2 fix): market 매개변수 추가.
    이전 버전은 항상 KR 만 반환 → US 백테스트에서 호출 시 universe 0 → trade 안 함.
    """
    ensure_table()
    with cursor() as con:
        # Build market filter
        if market == "kr":
            mkt_clause = "(ticker LIKE '%.KS' OR ticker LIKE '%.KQ')"
        elif market == "us":
            mkt_clause = "ticker NOT LIKE '%.KS' AND ticker NOT LIKE '%.KQ'"
        else:
            mkt_clause = "1=1"

        # KR delisted (currently only KR has delisted table populated)
        delisted_before = set(r[0] for r in con.execute(
            "SELECT ticker FROM delisted_tickers WHERE delisting_date <= ?",
            [date_str],
        ).fetchall())

        # Alive = ticker in prices on or before this date, minus delisted
        all_in_prices = set(r[0] for r in con.execute(
            f"SELECT DISTINCT ticker FROM prices WHERE {mkt_clause} "
            f"AND date <= ?",
            [date_str],
        ).fetchall())

    alive = sorted(all_in_prices - delisted_before)

    # 🚨 Fail-loud: if universe shrinks to near-empty, warn caller
    if market == "us" and len(alive) < 50:
        import warnings
        warnings.warn(
            f"universe_alive_at(market='us'): only {len(alive)} alive "
            f"tickers — likely no US delisted data ingested. Using "
            f"all US tickers as fallback.",
            stacklevel=2,
        )
    return alive


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--meta-only", action="store_true",
                    help="Only ingest metadata, skip price ingest")
    p.add_argument("--max", type=int, default=None,
                    help="Limit number of tickers (for testing)")
    p.add_argument("--min-date", type=str, default="2008-01-01")
    args = p.parse_args()

    n_meta = ingest_metadata(min_delist_date=args.min_date, verbose=True)
    print(f"\nMetadata: {n_meta} rows")
    if not args.meta_only:
        print(f"\nStarting price ingest …")
        counts = ingest_prices(min_delist_date=args.min_date,
                                max_tickers=args.max, verbose=True)
        print(f"Prices: {len(counts)} tickers with data")
