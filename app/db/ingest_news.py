"""DART disclosures → Supabase `disclosures` table.

News is fetched in real-time by the web app via `/api/news/[ticker]`
(Naver Finance 종목 뉴스 tab, 5-minute ISR cache), so this module no
longer touches the `news` table — only disclosures, which use a rate-
limited DART API key and benefit from the DB cache.

Usage:
    python -m app.db.ingest_news              # all KR tickers
    python -m app.db.ingest_news --tickers 005930.KS 035720.KS
    python -m app.db.ingest_news --limit 100   # smoke
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402

log = logging.getLogger("ingest_news")

DART_LIST = "https://opendart.fss.or.kr/api/list.json"


# ----------------------------------------------------------------------------
# DART disclosures (KR)
# ----------------------------------------------------------------------------

_dart_corp_code_cache: Optional[Dict[str, str]] = None


def _dart_corp_codes() -> Dict[str, str]:
    """Returns {stock_code (6-digit): corp_code (8-digit)}.

    Lazy-loads once per process. Reuses the existing local parquet cache from
    app.data.ingest_dart.fetch_corp_code_map() when available; otherwise fetches.
    """
    global _dart_corp_code_cache
    if _dart_corp_code_cache is not None:
        return _dart_corp_code_cache
    try:
        from app.data.ingest_dart import fetch_corp_code_map
        df = fetch_corp_code_map()
    except Exception as e:
        log.warning("DART corp_code map unavailable: %s", e)
        _dart_corp_code_cache = {}
        return _dart_corp_code_cache
    cache = {}
    for _, row in df.iterrows():
        sc = str(row.get("stock_code", "")).strip()
        cc = str(row.get("corp_code", "")).strip()
        if sc and cc and sc.isdigit() and len(sc) == 6:
            cache[sc] = cc
    _dart_corp_code_cache = cache
    log.info("DART corp_code map: %d entries", len(cache))
    return cache


def fetch_dart_disclosures(stock_code: str, days_back: int = 90,
                           max_retries: int = 3) -> List[Dict[str, Any]]:
    api_key = os.environ.get("DART_API_KEY")
    if not api_key:
        return []
    corp_codes = _dart_corp_codes()
    corp_code = corp_codes.get(stock_code)
    if not corp_code:
        return []
    end = date.today().strftime("%Y%m%d")
    start = (date.today() - timedelta(days=days_back)).strftime("%Y%m%d")
    last_err: Optional[str] = None
    for attempt in range(max_retries):
        try:
            r = requests.get(
                DART_LIST,
                params={"crtfc_key": api_key, "corp_code": corp_code,
                        "bgn_de": start, "end_de": end,
                        "page_count": 100, "sort": "date", "sort_mth": "desc"},
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
        except requests.exceptions.ConnectionError as e:
            # Connection reset (rate-limit). Exponential backoff.
            last_err = str(e)
            time.sleep(2 ** attempt)
            continue
        except Exception as e:
            log.debug("dart fetch %s: %s", stock_code, e)
            return []
        if data.get("status") == "020":
            # Daily quota exceeded — stop retrying, but caller can continue.
            log.warning("DART quota exceeded for %s", stock_code)
            return []
        if data.get("status") != "000":
            return []
        break
    else:
        log.debug("dart retries exhausted for %s: %s", stock_code, last_err)
        return []
    out = []
    for it in data.get("list", []):
        rcept = it.get("rcept_no", "")
        if not rcept:
            continue
        out.append({
            "rcept_no": rcept,
            "report_nm": it.get("report_nm", "").strip(),
            "report_type": it.get("pblntf_ty"),
            "filed_date": it.get("rcept_dt"),   # YYYYMMDD
            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept}",
        })
    return out


# ----------------------------------------------------------------------------
# DB upsert
# ----------------------------------------------------------------------------

def upsert_disclosures(ticker: str, items: List[Dict[str, Any]]) -> int:
    if not items:
        return 0
    rows = []
    for it in items:
        fd = it.get("filed_date") or ""
        try:
            filed = datetime.strptime(fd, "%Y%m%d").date() if fd else None
        except Exception:
            filed = None
        rows.append((
            ticker, it["rcept_no"], it["report_nm"], it.get("report_type"),
            filed, it.get("url"),
        ))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO disclosures
                  (ticker, rcept_no, report_nm, report_type, filed_date, url)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (rcept_no) DO NOTHING
                """,
                rows,
            )
    return len(rows)


# ----------------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------------

def _kr_tickers(limit: Optional[int]) -> List[str]:
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ticker FROM tickers "
                "WHERE is_active = true AND market IN ('KOSPI', 'KOSDAQ') "
                "ORDER BY ticker" + (f" LIMIT {int(limit)}" if limit else "")
            )
            return [r[0] for r in cur.fetchall()]


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", nargs="+", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--days-back", type=int, default=30)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    tickers = args.tickers or _kr_tickers(limit=args.limit)
    log.info("processing %d tickers", len(tickers))
    t0 = time.time()
    n_disc = 0
    for i, t in enumerate(tickers, 1):
        code = t.split(".")[0]
        if not t.endswith((".KS", ".KQ")):
            continue
        try:
            items = fetch_dart_disclosures(code, days_back=args.days_back)
            n_disc += upsert_disclosures(t, items)
            time.sleep(0.06)   # DART 1000 req/min cap
        except Exception as e:
            log.warning("dart %s: %s", t, e)
        if i % 100 == 0:
            log.info("  [%d/%d] disclosures=%d", i, len(tickers), n_disc)
    log.info("done in %.1fs: disclosures=%d", time.time() - t0, n_disc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
