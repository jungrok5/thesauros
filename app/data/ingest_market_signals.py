"""Ingest KR market signals — short sales, dividends, market warnings.

Schema lives in migrations/027_market_signals.sql. The companion UI
interpreter is web-next/src/lib/market-signals-interpret.ts.

Data sources:
  - 공매도 (shorting):   pykrx.stock.get_shorting_*
  - 배당 (dividends):    pykrx.stock.get_market_fundamental_by_date
                         + DART for ex-dividend date when available
  - 시장 경고 (warnings): Naver m.stock.naver.com integration page
                          parses 단기과열·관리·거래정지 labels.

Engagement-set filtered for KR universe + watchlist + recently-accessed
tickers to keep the daily-scan / weekly-fundamentals workloads bounded.

Usage:
    python -m app.data.ingest_market_signals              # all signals
    python -m app.data.ingest_market_signals --shorts      # one type
    python -m app.data.ingest_market_signals --tickers 005930.KS
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn  # noqa: E402

log = logging.getLogger("ingest_market_signals")


# ─────────────────────────────────────────────────────────────────────
# Ticker selection
# ─────────────────────────────────────────────────────────────────────

def _engagement_kr_tickers() -> List[str]:
    """KR universe (KOSPI/KOSDAQ active) ∪ watchlist (engaged).
    Same filter we use for bars/fundamentals to keep workload bounded.
    """
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ticker FROM (
                    SELECT ticker FROM tickers
                     WHERE is_active = true
                       AND market IN ('KOSPI', 'KOSDAQ')
                    UNION
                    SELECT ticker FROM watchlist
                     WHERE (category = 'holding'
                            OR last_accessed_at >= CURRENT_DATE - INTERVAL '90 days')
                       AND (ticker LIKE '%.KS' OR ticker LIKE '%.KQ')
                ) AS t
                """
            )
            return [r[0] for r in cur.fetchall()]


# ─────────────────────────────────────────────────────────────────────
# 공매도
# ─────────────────────────────────────────────────────────────────────

def _ingest_shorts_for_ticker(ticker: str, days_back: int = 30) -> int:
    """Pull recent shorting status (last `days_back` days) for one ticker."""
    code = ticker.split(".")[0]
    try:
        from pykrx import stock
    except ImportError:
        log.error("pykrx not installed")
        return 0
    end = date.today()
    start = end - timedelta(days=days_back)
    try:
        # `get_shorting_status_by_date` returns: 공매도 / 매수 / 잔고 / 비율.
        df = stock.get_shorting_status_by_date(
            start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code,
        )
    except Exception as e:
        log.debug("shorting %s failed: %s", ticker, e)
        return 0
    if df is None or df.empty:
        return 0
    rows: List[Tuple] = []
    for d_idx, row in df.iterrows():
        try:
            day = d_idx.date() if hasattr(d_idx, "date") else d_idx
            # pykrx column names: 공매도, 매수, 비중, 잔고 (조회 시점에 따라)
            short_vol = _first_nonneg(row, ("공매도", "공매도수량"))
            total_vol = _first_nonneg(row, ("거래량", "매수"))
            ratio = (
                short_vol / total_vol if (short_vol is not None and total_vol)
                else None
            )
            # Balance fields exist on the *balance* endpoint; fold a
            # second call below.
            rows.append((ticker, day, short_vol, None, total_vol, ratio,
                         None, None, None))
        except Exception:
            continue
    if not rows:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO short_sales
                  (ticker, day, short_volume, short_value, total_volume,
                   short_ratio, balance_shares, balance_value, balance_ratio)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, day) DO UPDATE SET
                  short_volume = EXCLUDED.short_volume,
                  total_volume = EXCLUDED.total_volume,
                  short_ratio = EXCLUDED.short_ratio,
                  updated_at = now()
                """,
                rows,
            )
    return len(rows)


def _first_nonneg(row, names: Tuple[str, ...]) -> Optional[int]:
    for n in names:
        if n in row.index:
            v = row[n]
            try:
                iv = int(v)
                if iv >= 0:
                    return iv
            except (TypeError, ValueError):
                continue
    return None


# ─────────────────────────────────────────────────────────────────────
# 배당
# ─────────────────────────────────────────────────────────────────────

def _ingest_dividend_for_ticker(ticker: str) -> int:
    """Latest dividend yield + DPS from pykrx; ex-dividend date heuristic.

    pykrx's `get_market_fundamental_by_date` returns DIV (수익률) + DPS
    (주당 배당금) per day. The "current" snapshot is what users want;
    we take the most recent trading day. Ex-dividend date is not in
    that endpoint — DART's company-info endpoint has it, but here we
    leave it null and the UI shows "next 배당락" as inferred from
    typical 12월 결산 timing.
    """
    code = ticker.split(".")[0]
    try:
        from pykrx import stock
    except ImportError:
        return 0
    end = date.today()
    start = end - timedelta(days=14)
    try:
        df = stock.get_market_fundamental_by_date(
            start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code,
        )
    except Exception as e:
        log.debug("fundamental %s failed: %s", ticker, e)
        return 0
    if df is None or df.empty:
        return 0
    latest = df.iloc[-1]
    dps = latest.get("DPS") if "DPS" in df.columns else None
    div = latest.get("DIV") if "DIV" in df.columns else None
    try:
        dps_v = float(dps) if dps is not None else None
        div_v = float(div) if div is not None else None
    except (TypeError, ValueError):
        return 0
    # Skip when company has no dividend at all (DPS == 0 and DIV == 0).
    if (dps_v in (None, 0)) and (div_v in (None, 0)):
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO dividend_info
                  (ticker, dps, yield_pct, ex_dividend, record_date, payment_date)
                VALUES (%s, %s, %s, NULL, NULL, NULL)
                ON CONFLICT (ticker) DO UPDATE SET
                  dps = EXCLUDED.dps,
                  yield_pct = EXCLUDED.yield_pct,
                  updated_at = now()
                """,
                (ticker, dps_v, div_v),
            )
    return 1


# ─────────────────────────────────────────────────────────────────────
# 시장 경고
# ─────────────────────────────────────────────────────────────────────

# Korean label → our enum level. Strict map — anything not here is
# ignored so a future Naver markup change can't smuggle in a new level
# we don't handle in the UI interpreter.
_WARNING_LABEL_MAP = {
    "거래정지": "trading_halt",
    "관리": "surveillance",
    "관리종목": "surveillance",
    "투자위험": "risk",
    "투자경고": "warning",
    "투자주의": "caution",
    "단기과열": "overheat",
    "단기과열종목": "overheat",
}

_NAVER_INTEGRATION_URL = "https://m.stock.naver.com/api/stock/{code}/integration"


def _ingest_warnings_for_ticker(ticker: str) -> int:
    """Scrape Naver's mobile stock page for the warning chips Korean
    investors see right next to the ticker name. The integration JSON
    has an `iconInfos` array — each entry's `code` field carries the
    label (\"투자경고\" 등).
    """
    code = ticker.split(".")[0]
    url = _NAVER_INTEGRATION_URL.format(code=code)
    try:
        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0",
                     "Referer": "https://m.stock.naver.com/"},
            timeout=8,
        )
    except requests.RequestException as e:
        log.debug("naver warnings %s: %s", ticker, e)
        return 0
    if r.status_code != 200:
        return 0
    try:
        payload = r.json()
    except ValueError:
        return 0
    icons = (payload or {}).get("iconInfos") or []
    found: List[Tuple[str, str, Optional[date], Optional[date]]] = []
    for it in icons:
        label = (it.get("code") or it.get("name") or "").strip()
        level = _WARNING_LABEL_MAP.get(label)
        if not level:
            continue
        # Naver may attach designation / expiry dates on some icons via
        # the `tooltip` field; parse YYYY.MM.DD ~ YYYY.MM.DD ranges.
        tooltip = (it.get("tooltip") or "")
        des, exp = _parse_warning_range(tooltip)
        found.append((level, tooltip or label, des, exp))

    # 1. Delete prior rows for this ticker so removals propagate.
    # 2. Insert current set.
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM market_warnings WHERE ticker = %s",
                        (ticker,))
            if found:
                cur.executemany(
                    """
                    INSERT INTO market_warnings
                      (ticker, level, reason, designated_at, expires_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (ticker, level) DO UPDATE SET
                      reason = EXCLUDED.reason,
                      designated_at = EXCLUDED.designated_at,
                      expires_at = EXCLUDED.expires_at,
                      updated_at = now()
                    """,
                    [(ticker, level, reason, des, exp)
                     for level, reason, des, exp in found],
                )
    return len(found)


_DATE_RE = re.compile(r"(\d{4}\.\d{2}\.\d{2})(?:\s*~\s*(\d{4}\.\d{2}\.\d{2}))?")


def _parse_warning_range(text: str) -> Tuple[Optional[date], Optional[date]]:
    if not text:
        return None, None
    m = _DATE_RE.search(text)
    if not m:
        return None, None
    try:
        d1 = datetime.strptime(m.group(1), "%Y.%m.%d").date()
    except ValueError:
        d1 = None
    d2 = None
    if m.group(2):
        try:
            d2 = datetime.strptime(m.group(2), "%Y.%m.%d").date()
        except ValueError:
            d2 = None
    return d1, d2


# ─────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────

def run_all(
    tickers: Optional[Iterable[str]] = None,
    do_shorts: bool = True,
    do_dividends: bool = True,
    do_warnings: bool = True,
    sleep_between: float = 0.1,
) -> dict:
    if tickers is None:
        tickers = _engagement_kr_tickers()
    tickers = list(tickers)
    log.info("ingest_market_signals: %d tickers", len(tickers))

    counts = {"shorts": 0, "dividends": 0, "warnings": 0, "errors": 0}
    for i, t in enumerate(tickers, 1):
        try:
            if do_shorts:
                counts["shorts"] += _ingest_shorts_for_ticker(t)
            if do_dividends:
                counts["dividends"] += _ingest_dividend_for_ticker(t)
            if do_warnings:
                counts["warnings"] += _ingest_warnings_for_ticker(t)
        except Exception as e:
            counts["errors"] += 1
            log.debug("ingest %s error: %s", t, e)
        time.sleep(sleep_between)
        if i % 100 == 0:
            log.info("  %d/%d  %s", i, len(tickers), counts)
    log.info("done: %s", counts)
    return counts


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", nargs="*", default=None)
    p.add_argument("--shorts-only", action="store_true")
    p.add_argument("--dividends-only", action="store_true")
    p.add_argument("--warnings-only", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    do_s = not (args.dividends_only or args.warnings_only)
    do_d = not (args.shorts_only or args.warnings_only)
    do_w = not (args.shorts_only or args.dividends_only)
    run_all(
        tickers=args.tickers,
        do_shorts=do_s,
        do_dividends=do_d,
        do_warnings=do_w,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
