"""One-shot cleanup to run RIGHT AFTER upgrading Supabase to Pro.

Sequence:
  1. DELETE bars_daily WHERE bar_date < CURRENT_DATE - INTERVAL '2 years'
  2. DELETE bars_daily WHERE ticker NOT IN (KR all + S&P 500)
  3. VACUUM FULL bars_daily (reclaims disk to OS)
  4. Verify size

After this, you can downgrade back to Free tier if total < 500MB.

Usage:
    python -m scripts.cleanup_after_pro              # dry-run (counts only)
    python -m scripts.cleanup_after_pro --execute    # actually delete + vacuum
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")

from app.db import get_conn                          # noqa: E402
from app.db.scan_daily import _list_tickers          # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--execute", action="store_true",
                   help="actually run DELETE + VACUUM FULL (default: dry-run)")
    p.add_argument("--years", type=int, default=2,
                   help="keep bars from the last N years (default 2)")
    args = p.parse_args(argv)

    keep = set(_list_tickers(
        markets=["KOSPI", "KOSDAQ", "NASDAQ", "NYSE", "AMEX", "ARCA", "BATS"],
        sp500_only=True,
    ))
    print(f"keep universe: {len(keep):,} tickers (KR all + S&P 500)")

    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            # Pre-flight: confirm DB is writable
            cur.execute("SHOW default_transaction_read_only")
            ro = cur.fetchone()[0]
            if ro == "on":
                print("[FAIL] DB still read-only - upgrade Supabase to Pro first")
                return 1

            cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
            print(f"DB size before: {cur.fetchone()[0]}")

            # 1) old bars
            cur.execute(
                f"SELECT COUNT(*) FROM bars_daily "
                f"WHERE bar_date < CURRENT_DATE - INTERVAL '{args.years} years'"
            )
            n_old = cur.fetchone()[0]
            print(f"  bars older than {args.years}y: {n_old:,} rows")

            # 2) non-universe
            cur.execute(
                "SELECT COUNT(*), COUNT(DISTINCT ticker) FROM bars_daily "
                "WHERE ticker != ALL(%s)",
                (list(keep),),
            )
            n_out, t_out = cur.fetchone()
            print(f"  bars outside universe: {n_out:,} rows ({t_out:,} tickers)")

            if not args.execute:
                print("\ndry-run only; pass --execute to apply")
                return 0

            print("\n→ DELETE old bars ...")
            t0 = time.time()
            cur.execute(
                f"DELETE FROM bars_daily "
                f"WHERE bar_date < CURRENT_DATE - INTERVAL '{args.years} years'"
            )
            print(f"  deleted {cur.rowcount:,} in {time.time()-t0:.1f}s")

            print("→ DELETE non-universe bars ...")
            t0 = time.time()
            cur.execute(
                "DELETE FROM bars_daily WHERE ticker != ALL(%s)",
                (list(keep),),
            )
            print(f"  deleted {cur.rowcount:,} in {time.time()-t0:.1f}s")

            print("→ VACUUM FULL bars_daily (may take 1-3 min) ...")
            t0 = time.time()
            cur.execute("VACUUM FULL bars_daily")
            print(f"  done in {time.time()-t0:.1f}s")

            cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
            print(f"DB size after: {cur.fetchone()[0]}")
            cur.execute(
                "SELECT pg_size_pretty(pg_total_relation_size('bars_daily')), "
                "COUNT(*), COUNT(DISTINCT ticker), MIN(bar_date), MAX(bar_date) "
                "FROM bars_daily"
            )
            s, n, t, a, b = cur.fetchone()
            print(f"bars_daily: {s} | {n:,} rows | {t:,} tickers | {a} ~ {b}")

    print("\n[OK] cleanup done. If DB size < 500MB you can downgrade to Free tier.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
