"""Ingest analyst consensus + target price (KR via Naver mobile).

Two Naver mobile endpoints feed this:

  finance.annual    → trTitleList[isConsensus='Y'] columns give
                      consensus EPS / revenue / op_income for forward
                      fiscal years (YYYYMM key).
  integration       → consensusInfo.priceTargetMean = analyst average
                      target price (the most visible number on the
                      stock detail page).

Why mobile API only: KRX is IP-blocked on cloud, and DART doesn't
publish consensus (only filed actuals). Naver mobile is the only
cloud-reachable source for forward estimates. The same _naver_get
retry wrapper as ingest_market_signals defends against transient
429/5xx.

Schema: see migrations/029_investor_intel.sql — analyst_consensus
PK = (ticker, fiscal_year).

usage:
    python -m app.data.ingest_consensus
    python -m app.data.ingest_consensus --tickers 005930.KS 035720.KS
    python -m app.data.ingest_consensus --limit 50
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.data.ingest_market_signals import (  # noqa: E402
    _engagement_kr_tickers,
    _naver_get,
)
from app.db import get_conn  # noqa: E402

log = logging.getLogger("ingest_consensus")

_FINANCE_ANNUAL_URL = (
    "https://m.stock.naver.com/api/stock/{code}/finance/annual"
)
_INTEGRATION_URL = "https://m.stock.naver.com/api/stock/{code}/integration"


def _to_float(v) -> Optional[float]:
    if v is None or v == "" or v == "-":
        return None
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _ingest_one(ticker: str) -> int:
    """Returns rows upserted (0 or 1+ per fiscal year, plus optional
    target-price refresh on the latest year).
    """
    code = ticker.split(".")[0]

    # ── Forward fiscal-year fundamentals from finance.annual ─────────
    annual = _naver_get(_FINANCE_ANNUAL_URL.format(code=code))
    rows_by_year: Dict[int, Dict[str, Optional[float]]] = {}

    if annual is not None:
        fi = annual.get("financeInfo") or {}
        titles = fi.get("trTitleList") or []
        # Naver labels columns with YYYYMM ("202612"). Take the year prefix.
        consensus_cols: List[str] = [
            t["key"] for t in titles if t.get("isConsensus") == "Y"
        ]
        # Title → field mapping. Korean labels are stable; the
        # _to_float wrapper tolerates missing values.
        field_map = {
            "매출액": "consensus_revenue",
            "영업이익": "consensus_op_income",
            "EPS": "consensus_eps",
        }
        for row in fi.get("rowList") or []:
            title = (row.get("title") or "").strip()
            field = field_map.get(title)
            if not field:
                continue
            cols = row.get("columns") or {}
            for key in consensus_cols:
                cell = cols.get(key)
                if not isinstance(cell, dict):
                    continue
                val = _to_float(cell.get("value"))
                if val is None:
                    continue
                try:
                    fiscal_year = int(key[:4])
                except (TypeError, ValueError):
                    continue
                rows_by_year.setdefault(fiscal_year, {})[field] = val

    # ── Target price + recommendation mean from integration ──────────
    target_price: Optional[float] = None
    integ = _naver_get(_INTEGRATION_URL.format(code=code))
    if integ is not None:
        ci = integ.get("consensusInfo") or {}
        target_price = _to_float(ci.get("priceTargetMean"))

    if not rows_by_year and target_price is None:
        return 0

    # Target price is a "current consensus snapshot" — attach to the
    # nearest forward fiscal year (or earliest year we have, falling
    # back to current+1 if no rows at all).
    if target_price is not None:
        if rows_by_year:
            anchor_year = min(rows_by_year.keys())
        else:
            from datetime import date
            anchor_year = date.today().year + 1
            rows_by_year[anchor_year] = {}
        rows_by_year[anchor_year]["target_price"] = target_price

    # Upsert each fiscal_year row. PARTIAL updates: if Naver gives only
    # EPS this run and revenue next run, we want both to coexist —
    # use COALESCE so a None doesn't overwrite a prior value.
    written = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for fy, fields in rows_by_year.items():
                cur.execute(
                    """
                    INSERT INTO analyst_consensus
                      (ticker, fiscal_year, consensus_eps,
                       consensus_revenue, consensus_op_income, target_price)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ticker, fiscal_year) DO UPDATE SET
                      consensus_eps =
                        COALESCE(EXCLUDED.consensus_eps, analyst_consensus.consensus_eps),
                      consensus_revenue =
                        COALESCE(EXCLUDED.consensus_revenue, analyst_consensus.consensus_revenue),
                      consensus_op_income =
                        COALESCE(EXCLUDED.consensus_op_income, analyst_consensus.consensus_op_income),
                      target_price =
                        COALESCE(EXCLUDED.target_price, analyst_consensus.target_price),
                      updated_at = now()
                    """,
                    (
                        ticker,
                        fy,
                        fields.get("consensus_eps"),
                        fields.get("consensus_revenue"),
                        fields.get("consensus_op_income"),
                        fields.get("target_price"),
                    ),
                )
                written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", nargs="*", help="Subset; default = engagement KR set")
    p.add_argument("--limit", type=int, default=0, help="Cap N tickers (debug)")
    p.add_argument("--sleep", type=float, default=0.15,
                   help="Sleep between tickers — Naver is best-effort.")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    tickers = args.tickers or _engagement_kr_tickers()
    if args.limit:
        tickers = tickers[: args.limit]
    log.info("consensus ingest — %d tickers", len(tickers))

    total = 0
    fails = 0
    for i, t in enumerate(tickers, 1):
        try:
            n = _ingest_one(t)
            total += n
        except Exception as e:
            fails += 1
            log.warning("ticker=%s error: %s", t, e)
        if i % 100 == 0:
            log.info("  progress: %d/%d (%d rows written, %d fails)",
                     i, len(tickers), total, fails)
        time.sleep(args.sleep)

    log.info("done — %d rows across %d tickers (%d fails)",
             total, len(tickers), fails)
    return 0


if __name__ == "__main__":
    sys.exit(main())
