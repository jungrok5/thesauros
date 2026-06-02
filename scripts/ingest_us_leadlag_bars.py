"""Ingest US lead-lag bars for KR backtest factor.

Local Windows IP bypasses Azure-blocked Yahoo (verified 2026-06-02).
Pulls daily OHLC, resamples to W/M, stores in data/us_leadlag.duckdb
(separate from main backtest.duckdb to keep US data isolated).

US tickers chosen as plausible upstream leads for KR industry baskets:
  MU, NVDA, AMD, INTC, MRVL          → HBM / DRAM (Hynix 000660.KS)
  AAPL, TSM, ASML, AVGO              → 부품/파운드리 (Samsung 005930.KS)
  TSLA                                → 배터리 (LG엔솔 373220, 삼성SDI 006400, SK이노 096770)
  MSFT, GOOGL                         → AI 인프라 (NAVER 035420, Kakao 035720)
  QCOM                                → 모바일 칩 (Samsung)

Run once. Idempotent.
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")
sys.path.insert(0, str(_ROOT))

from app.backtest import local_store
from app.db.ingest_bars import _resample_daily_to_rows

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("ingest_us_leadlag")


US_TICKERS = [
    "MU", "NVDA", "AMD", "INTC", "MRVL",
    "AAPL", "TSM", "ASML", "AVGO",
    "TSLA",
    "MSFT", "GOOGL", "QCOM",
]


def main() -> int:
    db_path = _ROOT / "data" / "us_leadlag.duckdb"
    n_bars_total = 0
    t0 = time.time()
    with local_store.connect(db_path) as conn:
        for sym in US_TICKERS:
            try:
                df = yf.download(sym, start="2009-01-01", end="2026-05-22",
                                 progress=False, auto_adjust=False)
                if df is None or df.empty:
                    log.warning("%s: empty", sym); continue
                # Flatten multiindex columns from yfinance new API
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.rename(columns={c: c.lower() for c in df.columns})
                df = df[df["close"] > 0]
                rows = _resample_daily_to_rows(sym, df)
                if not rows: continue
                df_bars = pd.DataFrame(rows, columns=[
                    "ticker", "granularity", "bar_date",
                    "open", "high", "low", "close", "adj_close", "volume",
                ])
                local_store.upsert_bars(conn, sym, df_bars)
                n_bars_total += len(rows)
                log.info("%s: %d bars (%.1fs total)", sym, len(rows),
                         time.time() - t0)
            except Exception as e:
                log.warning("%s: ERROR %s", sym, str(e)[:80])

    log.info("DONE — %d total bars in %.1fs to %s",
             n_bars_total, time.time()-t0, db_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
