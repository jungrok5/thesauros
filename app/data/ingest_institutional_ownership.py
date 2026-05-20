"""Ingest institutional holders — DART 5% 대량보유 보고.

DART openAPI endpoint `majorstock.json` returns every "5% 보고" filing
for a given corp_code. Each filing represents a holder whose ownership
crossed 5% (or moved ≥1pp from their last reported level). This is the
authoritative public record of who owns what slice of a KR-listed
corp — 국민연금, 대형 자산운용사, 기관, 외인 펀드 등.

Schema: see migrations/029_investor_intel.sql — primary key is
(ticker, holder_name, reported_date) so re-runs are idempotent.

usage:
    python -m app.data.ingest_institutional_ownership
    python -m app.data.ingest_institutional_ownership --tickers 005930.KS
    python -m app.data.ingest_institutional_ownership --limit 100
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.config import DART_API_KEY  # noqa: E402
from app.data.ingest_dart import fetch_corp_code_map  # noqa: E402
from app.data.ingest_market_signals import _engagement_kr_tickers  # noqa: E402
from app.db import get_conn  # noqa: E402

log = logging.getLogger("ingest_institutional_ownership")

_DART_URL = "https://opendart.fss.or.kr/api/majorstock.json"

# Holder name → classification. Substring match (longest-first below).
# 'NPS' / 국민연금공단 is the most important to surface because the
# site has a "큰손 따라보기" framing.
_HOLDER_TYPE_RULES: list[tuple[str, str]] = [
    ("국민연금", "NPS"),
    ("자산운용", "AMC"),
    ("운용", "AMC"),
    ("인베스트먼트", "AMC"),
    ("Investment", "AMC"),
    ("자산", "AMC"),
    ("Capital", "FUND"),
    ("Fund", "FUND"),
    ("Partners", "FUND"),
    ("증권", "AMC"),
]


def _classify(holder_name: str) -> str:
    name = (holder_name or "").strip()
    if not name:
        return "OTHER"
    for needle, typ in _HOLDER_TYPE_RULES:
        if needle.lower() in name.lower():
            return typ
    return "OTHER"


def _to_int(v) -> Optional[int]:
    if v is None or v == "" or v == "-":
        return None
    try:
        return int(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _to_float(v) -> Optional[float]:
    if v is None or v == "" or v == "-":
        return None
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _ingest_one(ticker: str, corp_code: str) -> int:
    """Returns rows upserted. One DART call per ticker — list of all
    historical 5% reports for that corp. We KEEP the historical rows
    because they show flow ("국민연금 작년 6월부터 줄이는 중"). Retention
    sweeps anything older than 2 years.
    """
    params = {"crtfc_key": DART_API_KEY, "corp_code": corp_code}
    try:
        r = requests.get(_DART_URL, params=params, timeout=10)
    except requests.RequestException as e:
        log.info("ticker=%s DART error: %s", ticker, e)
        return 0
    if not r.ok:
        return 0
    try:
        data = r.json()
    except ValueError:
        return 0
    # status 013 = "조회된 데이타가 없습니다" — not an error, just no 5%
    # holder ever crossed the threshold (small caps especially).
    if data.get("status") != "000":
        return 0

    items = data.get("list") or []
    if not items:
        return 0

    rows: list[tuple] = []
    for it in items:
        holder = (it.get("repror") or "").strip()
        if not holder:
            continue
        reported_str = (it.get("rcept_dt") or "").strip()
        try:
            reported_date = datetime.strptime(reported_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        shares = _to_int(it.get("stkqy"))
        share_pct = _to_float(it.get("stkrt"))
        rcept_no = (it.get("rcept_no") or "").strip() or None
        holder_type = _classify(holder)
        rows.append((
            ticker, holder, holder_type, shares, share_pct,
            reported_date, rcept_no,
        ))

    if not rows:
        return 0

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO institutional_ownership
                  (ticker, holder_name, holder_type, shares, share_pct,
                   reported_date, rcept_no)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, holder_name, reported_date) DO UPDATE SET
                  holder_type = EXCLUDED.holder_type,
                  shares = EXCLUDED.shares,
                  share_pct = EXCLUDED.share_pct,
                  rcept_no = EXCLUDED.rcept_no,
                  updated_at = now()
                """,
                rows,
            )
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", nargs="*")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--sleep", type=float, default=0.12,
                   help="Sleep between calls — DART allows 10k/day; 0.12s "
                        "is safely under the per-second cap.")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if not DART_API_KEY:
        log.error("DART_API_KEY not set")
        return 1

    # Build stock_code → corp_code lookup once.
    cmap = fetch_corp_code_map()
    by_stock: dict[str, str] = {
        sc: cc for sc, cc in zip(cmap["stock_code"], cmap["corp_code"]) if sc
    }

    tickers = args.tickers or _engagement_kr_tickers()
    if args.limit:
        tickers = tickers[: args.limit]
    log.info("institutional ownership ingest — %d tickers", len(tickers))

    total = 0
    fails = 0
    no_corp = 0
    for i, t in enumerate(tickers, 1):
        stock_code = t.split(".")[0]
        corp_code = by_stock.get(stock_code)
        if not corp_code:
            no_corp += 1
            continue
        try:
            n = _ingest_one(t, corp_code)
            total += n
        except Exception as e:
            fails += 1
            log.warning("ticker=%s error: %s", t, e)
        if i % 100 == 0:
            log.info("  progress: %d/%d  rows=%d fails=%d no_corp=%d",
                     i, len(tickers), total, fails, no_corp)
        time.sleep(args.sleep)

    log.info("done — %d rows across %d tickers (%d fails, %d no corp_code)",
             total, len(tickers), fails, no_corp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
