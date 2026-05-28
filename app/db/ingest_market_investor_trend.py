"""Market-wide investor trend ingest → `market_investor_trend` table.

Source: https://m.stock.naver.com/api/index/{KOSPI|KOSDAQ}/integration

The `dealTrendInfo` field on the integration JSON gives today's net
buying for 개인 / 외국인 / 기관계 across the entire index. Values are
KRW 백만 (million won), signed (+ buy / - sell).

Why only this endpoint:
  - finance.naver.com/sise/investorDealTrendDay.naver returns empty
    body for all bizdate values (verified 2026-05-28 via Playwright).
  - 7-type breakdown (금융투자/투신/사모/etc) is not available from
    any cloud-reachable Naver endpoint.
  - KRX is cloud-blocked (Azure IP filter).

Backfill: not possible — this endpoint only returns today's snapshot.
Daily cron writes one row per (market, day). History grows from
deployment date forward.

Usage:
    python -m app.db.ingest_market_investor_trend
    python -m app.db.ingest_market_investor_trend --markets KOSPI
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402

log = logging.getLogger("ingest_market_investor_trend")

NAVER_URL = "https://m.stock.naver.com/api/index/{market}/integration"
KST = timezone(timedelta(hours=9))
MARKETS = ("KOSPI", "KOSDAQ")


def _parse_signed_int(s: object) -> Optional[int]:
    """Parse '+36,146' / '-10,422' / '+381' → int. Returns None on bad input."""
    if s is None:
        return None
    txt = str(s).strip().replace(",", "")
    if not txt:
        return None
    try:
        return int(float(txt))
    except (ValueError, TypeError):
        return None


def _parse_bizdate(s: object) -> Optional[str]:
    """'20260528' → '2026-05-28'. Falls back to today (KST) on bad input."""
    if s is None:
        return None
    txt = str(s).strip()
    if len(txt) == 8 and txt.isdigit():
        return f"{txt[0:4]}-{txt[4:6]}-{txt[6:8]}"
    return None


def fetch_one(market: str) -> Optional[Tuple[str, str, int, int, int]]:
    """Returns (market, day_iso, personal, foreign, institution) or None."""
    url = NAVER_URL.format(market=market)
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        body = r.json()
    except Exception as e:
        log.warning("%s fetch failed: %s", market, e)
        return None
    info = body.get("dealTrendInfo") or {}
    bizdate = _parse_bizdate(info.get("bizdate"))
    if not bizdate:
        log.warning("%s missing/invalid bizdate: %r", market, info.get("bizdate"))
        return None
    p = _parse_signed_int(info.get("personalValue"))
    f = _parse_signed_int(info.get("foreignValue"))
    i = _parse_signed_int(info.get("institutionalValue"))
    if p is None and f is None and i is None:
        log.warning("%s all values null", market)
        return None
    return (market, bizdate, p, f, i)


def upsert(rows: Iterable[Tuple[str, str, Optional[int], Optional[int], Optional[int]]]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO market_investor_trend
                  (market, day, individual_net, foreign_net, institution_net)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (market, day) DO UPDATE SET
                  individual_net  = EXCLUDED.individual_net,
                  foreign_net     = EXCLUDED.foreign_net,
                  institution_net = EXCLUDED.institution_net
                """,
                rows,
            )
    return len(rows)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--markets", nargs="+", default=list(MARKETS),
                   choices=list(MARKETS))
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    rows: List[Tuple[str, str, Optional[int], Optional[int], Optional[int]]] = []
    for m in args.markets:
        row = fetch_one(m)
        if row is not None:
            rows.append(row)
            log.info("%s %s: 개인=%s 외국인=%s 기관=%s",
                     row[0], row[1], row[2], row[3], row[4])
    n = upsert(rows)
    log.info("upserted %d row(s)", n)
    return 0 if n == len(args.markets) else 1


if __name__ == "__main__":
    sys.exit(main())
