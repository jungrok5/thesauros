"""Crawl today's market cap for every ticker in factors_eval, via Naver
mobile API. Used by Phase 4 grid search (lookahead bias: today's snapshot
applied to 17y backtest — same trade-off as Phase 1+2 quality scores).

Output: data/market_caps_today.csv  (ticker, market_cap_krw)
"""
from __future__ import annotations

import csv
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.connection import get_conn
from app.db.eval_financials import _naver_market_cap

OUT_CSV = ROOT / "data" / "market_caps_today.csv"
WORKERS = 16


def fetch_one(ticker: str):
    code = ticker.split(".")[0]
    try:
        mc = _naver_market_cap(code)
    except Exception as e:
        return ticker, None, str(e)
    return ticker, mc, None


def main() -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT ticker FROM factors_eval ORDER BY ticker")
        tickers = [t for (t,) in cur.fetchall()]
    print(f"crawling {len(tickers):,} tickers with {WORKERS} workers ...",
          flush=True)

    results: dict[str, float | None] = {}
    errors: list[tuple[str, str]] = []
    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch_one, t): t for t in tickers}
        for f in as_completed(futs):
            ticker, mc, err = f.result()
            results[ticker] = mc
            if err:
                errors.append((ticker, err))
            done += 1
            if done % 200 == 0:
                rate = done / (time.time() - t0)
                eta = (len(tickers) - done) / rate
                print(f"  {done:>5,}/{len(tickers):,}  "
                      f"({rate:.1f}/s, eta {eta:.0f}s)", flush=True)

    elapsed = time.time() - t0
    have = sum(1 for v in results.values() if v is not None)
    print(f"\ndone in {elapsed:.0f}s  ({have:,}/{len(tickers):,} with cap)",
          flush=True)
    if errors:
        print(f"  errors: {len(errors)} (first 5: {errors[:5]})", flush=True)

    OUT_CSV.parent.mkdir(exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["ticker", "market_cap_krw"])
        for t in tickers:
            mc = results.get(t)
            w.writerow([t, f"{mc:.0f}" if mc is not None else ""])
    print(f"wrote {OUT_CSV}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
