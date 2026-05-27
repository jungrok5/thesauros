"""One-shot backfill: read data/market_caps_today.csv (produced by
crawl_market_caps.py) and write each value into factors_eval.market_cap.

After migration 053 adds the column, this populates it. Going forward,
the daily eval pipeline (eval_financials.py) maintains the column via
its upsert path.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.connection import get_conn

CSV_PATH = ROOT / "data" / "market_caps_today.csv"


def main() -> int:
    if not CSV_PATH.exists():
        print(f"missing {CSV_PATH} — run scripts/crawl_market_caps.py first")
        return 1

    rows: list[tuple[str, float]] = []
    with CSV_PATH.open("r", encoding="utf-8", newline="") as fp:
        for row in csv.DictReader(fp):
            v = (row.get("market_cap_krw") or "").strip()
            if not v:
                continue
            try:
                rows.append((row["ticker"], float(v)))
            except ValueError:
                pass

    print(f"loaded {len(rows):,} market caps from CSV", flush=True)

    updated = 0
    with get_conn() as conn, conn.cursor() as cur:
        for ticker, cap in rows:
            cur.execute(
                "UPDATE factors_eval SET market_cap = %s "
                "WHERE ticker = %s AND market_cap IS DISTINCT FROM %s",
                (cap, ticker, cap),
            )
            updated += cur.rowcount
        conn.commit()
    print(f"updated {updated:,} factors_eval rows", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
