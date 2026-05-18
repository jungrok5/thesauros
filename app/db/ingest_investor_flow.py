"""Investor flow ingest → `investor_flow` table.

Source: Naver Finance per-stock 외국인·기관 page
    https://finance.naver.com/item/frgn.naver?code={code}&page={n}

The previous implementation used the KIS `inquire-investor` endpoint,
which on the vts (모의투자) tier returns 500 Server Error for many
large caps (SK하이닉스 / 기아 / etc.) and empty fields for others.
Coverage stalled at ~50% of the KR universe.

Naver Finance's foreign/institution table is the same data displayed
on every retail brokerage in Korea — covers the full KOSPI/KOSDAQ
universe, is rate-friendly, and needs no API key.

Schema mapping (Naver gives **shares**, not KRW):
    foreign_shares_net      ← 외국인 순매매 (단위: 주)
    institution_shares_net  ← 기관 순매매
    individual_shares_net   ← derived: −(foreign + institution)
    foreign_net (KRW)       ← shares × close   (approx.)
    institution_net (KRW)   ← shares × close
    individual_net (KRW)    ← shares × close

The `_net` (KRW) fields are derived using daily close, so they are
approximations of intraday-weighted mean. Magnitude is correct,
direction is correct, granularity is "close × shares" — sufficient
for the dashboard's 5-day net buying view.

Usage:
    python -m app.db.ingest_investor_flow             # all KR active
    python -m app.db.ingest_investor_flow --tickers 005930.KS
    python -m app.db.ingest_investor_flow --limit 100
    python -m app.db.ingest_investor_flow --pages 3   # ~30 trading days
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402

log = logging.getLogger("ingest_investor_flow")

NAVER_FRGN_URL = (
    "https://finance.naver.com/item/frgn.naver?code={code}&page={page}"
)

# The 외국인·기관 table on the Naver frgn page is the 5th `<table>` block
# (index 4). Its caption literally contains "외국인" so we match by
# caption instead of position, which survives layout shuffles.
TABLE_RE = re.compile(
    r"<table[^>]*>([\s\S]*?)</table>", re.IGNORECASE,
)
ROW_RE = re.compile(
    r'<tr\s+onMouseOver="mouseOver[\s\S]*?</tr>', re.IGNORECASE,
)
SPAN_NUMBER_RE = re.compile(
    r'<span[^>]*class="[^"]*tah[^"]*"[^>]*>\s*([\-+]?[0-9,.]+)%?\s*</span>',
    re.IGNORECASE,
)
DATE_RE = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})")


def _kr_code(ticker: str) -> Optional[str]:
    if "." not in ticker:
        return None
    code, suffix = ticker.split(".", 1)
    if suffix in ("KS", "KQ") and code.isdigit() and len(code) == 6:
        return code
    return None


def _parse_num(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    s = s.replace(",", "").strip()
    if not s or s == "-":
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def fetch_naver_page(code: str, page: int) -> List[Dict[str, Any]]:
    """Parse one page of the foreign/institution table. Returns a list of
    {day, close, foreign_shares, institution_shares} dicts."""
    url = NAVER_FRGN_URL.format(code=code, page=page)
    try:
        r = requests.get(
            url, timeout=15,
            headers={
                "User-Agent":
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                "Referer": "https://finance.naver.com/",
            },
        )
        r.raise_for_status()
        r.encoding = "euc-kr"
        html = r.text
    except Exception as e:
        log.debug("naver fetch %s p%d: %s", code, page, e)
        return []

    # Find the table whose caption mentions 외국인 (the 거래량 column on the
    # 거래원 table also has the word; pick the one with the `title1` rowspan
    # header pattern unique to this layout).
    target_tbl: Optional[str] = None
    for tbl in TABLE_RE.findall(html):
        if "외국인" in tbl and 'class="title1"' in tbl and "보유율" in tbl:
            target_tbl = tbl
            break
    if not target_tbl:
        return []

    out: List[Dict[str, Any]] = []
    for tr in ROW_RE.findall(target_tbl):
        # Date is a plain text in the first td.
        date_m = DATE_RE.search(tr)
        if not date_m:
            continue
        y, mo, d = date_m.groups()
        try:
            day = datetime(int(y), int(mo), int(d)).date()
        except ValueError:
            continue

        # All <span class="tah ..."> matches in row order. The date span
        # has class "tah p10 gray03" so it gets captured first; subsequent
        # spans are: close, prev_diff (unsigned, ignore), change%, volume,
        # institution_net, foreign_net, foreign_holdings, foreign_pct.
        nums = SPAN_NUMBER_RE.findall(tr)
        if len(nums) < 7:
            continue
        close = _parse_num(nums[1])
        inst  = _parse_num(nums[5])
        frgn  = _parse_num(nums[6])
        if close is None:
            continue
        out.append({
            "day": day,
            "close": close,
            "institution_shares": inst,
            "foreign_shares": frgn,
        })
    return out


def fetch_for_ticker(ticker: str, pages: int) -> List[Tuple[Any, ...]]:
    """All pages → upsert rows. Pages of ~10 rows each."""
    code = _kr_code(ticker)
    if not code:
        return []
    rows: List[Tuple[Any, ...]] = []
    for page in range(1, pages + 1):
        items = fetch_naver_page(code, page)
        if not items:
            break          # End of history (or fetch error) → stop early.
        for it in items:
            close = it["close"]
            fs = it["foreign_shares"]
            iss = it["institution_shares"]
            # individual = −(foreign + institution) approximation
            ps = None
            if fs is not None and iss is not None:
                ps = -(fs + iss)
            fnet = fs * close if fs is not None else None
            inet = iss * close if iss is not None else None
            pnet = ps * close if ps is not None else None
            rows.append((
                ticker, it["day"],
                fnet, inet, pnet,
                None,           # program_net (Naver doesn't surface)
                fs, iss, ps,
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
                  foreign_net           = EXCLUDED.foreign_net,
                  institution_net       = EXCLUDED.institution_net,
                  individual_net        = EXCLUDED.individual_net,
                  foreign_shares_net    = EXCLUDED.foreign_shares_net,
                  institution_shares_net= EXCLUDED.institution_shares_net,
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
    p.add_argument("--pages", type=int, default=3,
                   help="Naver pages per ticker (each ≈ 10 rows). Default 3 = ~30 days")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--throttle-ms", type=int, default=80,
                   help="per-worker sleep between requests (Naver-friendly pacing)")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    targets = args.tickers or _kr_tickers(args.limit)
    log.info("Naver investor flow: %d tickers × %d page(s)",
             len(targets), args.pages)

    t0 = time.time()
    n_total = 0
    n_ok = n_err = 0
    BATCH = 600
    buffer: List[Tuple[Any, ...]] = []

    def _worker(t: str) -> List[Tuple[Any, ...]]:
        try:
            rows = fetch_for_ticker(t, args.pages)
            time.sleep(args.throttle_ms / 1000)
            return rows
        except Exception as e:
            log.debug("err %s: %s", t, e)
            return []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_worker, t): t for t in targets}
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                rows = fut.result()
                if rows:
                    buffer.extend(rows)
                    n_ok += 1
                else:
                    n_err += 1
            except Exception:
                n_err += 1
            if len(buffer) >= BATCH:
                n_total += upsert(buffer)
                buffer.clear()
            if i % 200 == 0:
                log.info("  [%d/%d] flushed=%d ok=%d empty=%d",
                         i, len(targets), n_total, n_ok, n_err)
    if buffer:
        n_total += upsert(buffer)
    log.info("done in %.1fs: rows=%d ok=%d empty/err=%d",
             time.time() - t0, n_total, n_ok, n_err)
    return 0


if __name__ == "__main__":
    sys.exit(main())
