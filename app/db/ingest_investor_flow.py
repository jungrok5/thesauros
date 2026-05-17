"""KIS investor flow ingest → investor_flow table.

KIS /api/v1/quotations/inquire-investor returns the latest 30 trading
days of foreign / institution / individual net buying for one ticker.
We iterate active KR tickers, hit the endpoint, upsert all 30 days.

Performance:
  - KIS paper-trading rate cap: ~20 req/sec per app key. We pace
    at 60ms/req = 16.7/s for safety margin.
  - 3,000 KR tickers × 60ms ≈ 3 minutes per run.

Usage:
    python -m app.db.ingest_investor_flow                  # all KR
    python -m app.db.ingest_investor_flow --tickers 005930.KS
    python -m app.db.ingest_investor_flow --limit 100      # smoke
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402

log = logging.getLogger("ingest_investor_flow")


def _parse_int(s: Any) -> Optional[int]:
    if s is None or s == "":
        return None
    try:
        return int(str(s).replace(",", ""))
    except (ValueError, TypeError):
        return None


def fetch_one(client, ticker: str) -> List[Tuple[Any, ...]]:
    """Returns rows formatted for executemany."""
    code = ticker.split(".")[0]
    try:
        raw = client.investor_flow(code)
    except Exception as e:
        log.debug("kis %s: %s", ticker, e)
        return []
    rows = []
    for r in raw:
        ds = r.get("stck_bsop_date")
        if not ds or len(ds) != 8:
            continue
        try:
            day = datetime.strptime(ds, "%Y%m%d").date()
        except ValueError:
            continue
        rows.append((
            ticker, day,
            # 거래대금 단위 환산 (KIS 는 KRW 단위로 보고, 백만원 환산은 UI에서)
            _parse_int(r.get("frgn_ntby_tr_pbmn")),
            _parse_int(r.get("orgn_ntby_tr_pbmn")),
            _parse_int(r.get("prsn_ntby_tr_pbmn")),
            None,                                    # program_net (별도 endpoint, 향후)
            _parse_int(r.get("frgn_ntby_qty")),
            _parse_int(r.get("orgn_ntby_qty")),
            _parse_int(r.get("prsn_ntby_qty")),
        ))
    return rows


def upsert(rows: List[Tuple[Any, ...]]) -> int:
    if not rows:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO investor_flow
                  (ticker, day, foreign_net, institution_net, individual_net,
                   program_net, foreign_shares_net, institution_shares_net,
                   individual_shares_net)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, day) DO UPDATE SET
                  foreign_net = EXCLUDED.foreign_net,
                  institution_net = EXCLUDED.institution_net,
                  individual_net = EXCLUDED.individual_net,
                  foreign_shares_net = EXCLUDED.foreign_shares_net,
                  institution_shares_net = EXCLUDED.institution_shares_net,
                  individual_shares_net = EXCLUDED.individual_shares_net
                """,
                rows,
            )
    return len(rows)


def _kr_tickers(limit: Optional[int]) -> List[str]:
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            sql = ("SELECT ticker FROM tickers "
                   "WHERE is_active = true AND market IN ('KOSPI','KOSDAQ') "
                   "ORDER BY ticker")
            if limit:
                sql += f" LIMIT {int(limit)}"
            cur.execute(sql)
            return [r[0] for r in cur.fetchall()]


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", nargs="+", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--throttle-ms", type=int, default=60)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    from app.data.kis import KISClient
    try:
        client = KISClient()
    except Exception as e:
        log.error("KIS init failed: %s", e)
        return 1

    targets = args.tickers or _kr_tickers(args.limit)
    log.info("ingesting investor flow for %d tickers", len(targets))

    t0 = time.time()
    total_rows = 0
    n_ok = n_err = 0
    BATCH = 500
    buffer: List[Tuple[Any, ...]] = []
    for i, t in enumerate(targets, 1):
        try:
            rows = fetch_one(client, t)
            buffer.extend(rows)
            n_ok += 1 if rows else 0
        except Exception as e:
            log.debug("err %s: %s", t, e)
            n_err += 1
        # Flush every BATCH ticker results to keep memory bounded.
        if len(buffer) >= BATCH:
            total_rows += upsert(buffer)
            buffer.clear()
        time.sleep(args.throttle_ms / 1000)
        if i % 100 == 0:
            log.info("  [%d/%d] flushed=%d ok=%d err=%d",
                     i, len(targets), total_rows, n_ok, n_err)
    total_rows += upsert(buffer)
    log.info("done in %.1fs: rows=%d ok=%d err=%d",
             time.time() - t0, total_rows, n_ok, n_err)
    return 0


if __name__ == "__main__":
    sys.exit(main())
