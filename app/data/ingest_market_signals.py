"""Ingest KR market signals — market warnings + dividends.

⚠️ Data-source policy (2026-05-20 — pykrx 영구 폐기 후 확정):

  KRX (pykrx 가 호출하는 거래소 공식 endpoint) 는 비-KR cloud IP 전부
  차단. GH Actions, Vercel, AWS, Azure, GCP 모두 같음. 정책상 KRX 는
  라이센스 받은 기관/증권사용 데이터 통로지 자유 scraping 대상 X.

  남은 cloud-reachable 데이터 소스:

    1. **DART OpenAPI** (공식, API key 등록, 무료) — 가장 안정.
       공시 + 사업보고서 detail (재무, 배당, 5% 지분 변동) 모두 커버.

    2. **Naver Finance mobile API** (비공식, 정책 변경 위험) — 시가총액
       / 시세 / 일부 metadata 가용. 공식 API 아니므로 언제든 막힐 수
       있어 retry + backoff 로 보호 + DART 가 커버 안 하는 데이터만 사용.

    3. **FinanceDataReader** (cloud 작동) — KR 일봉 fallback 으로 사용 중.

  소스별 데이터 매핑:

    배당 (dividend_info)    : Naver finance.annual `주당배당금` (yearly)
                              실시간성 X. 향후 DART cashDividend 추가 검토.
    시장 경고 (market_warn) : Naver integration `iconInfos`
                              KRX 외엔 다른 소스 없음 — Naver 막히면 손실.
    공매도 (short_sales)    : **포기**. KRX 전용, cloud-reachable 소스
                              0. UI 카드는 데이터 없으면 자동 hide.

usage:
    python -m app.data.ingest_market_signals
    python -m app.data.ingest_market_signals --tickers 005930.KS
    python -m app.data.ingest_market_signals --dividends-only
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn  # noqa: E402

log = logging.getLogger("ingest_market_signals")

_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://m.stock.naver.com/",
}
_INTEGRATION_URL = "https://m.stock.naver.com/api/stock/{code}/integration"
_FINANCE_ANNUAL_URL = (
    "https://m.stock.naver.com/api/stock/{code}/finance/annual"
)


def _naver_get(url: str, max_retries: int = 3) -> Optional[dict]:
    """GET with exponential backoff + jitter — defends against Naver
    transient rate-limiting (429) or short outages (5xx). Returns parsed
    JSON dict or None on terminal failure. We log failures at INFO level
    only when ALL retries are exhausted; transient retries stay quiet.
    """
    import random
    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=8)
        except requests.RequestException as e:
            if attempt + 1 == max_retries:
                log.info("naver GET %s exhausted retries: %s", url, e)
                return None
            time.sleep((2 ** attempt) + random.random())
            continue
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError:
                return None
        # 429 / 5xx — back off; 4xx other — give up.
        if r.status_code == 429 or r.status_code >= 500:
            if attempt + 1 == max_retries:
                log.info("naver %s → %d (exhausted)", url, r.status_code)
                return None
            time.sleep((2 ** attempt) + random.random())
            continue
        # 4xx other (404 etc.) — no retry.
        return None
    return None


# ─────────────────────────────────────────────────────────────────────
# Ticker selection
# ─────────────────────────────────────────────────────────────────────

def _engagement_kr_tickers() -> List[str]:
    """KR universe ∪ engaged watchlist — same filter as bars/fundamentals."""
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
# 시장 경고 (Naver iconInfos)
# ─────────────────────────────────────────────────────────────────────

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


def _ingest_warnings_for_ticker(ticker: str) -> int:
    code = ticker.split(".")[0]
    payload = _naver_get(_INTEGRATION_URL.format(code=code))
    if payload is None:
        return 0
    icons = payload.get("iconInfos") or []
    found: List[Tuple[str, str, Optional[date], Optional[date]]] = []
    for it in icons:
        label = (it.get("code") or it.get("name") or "").strip()
        level = _WARNING_LABEL_MAP.get(label)
        if not level:
            continue
        tooltip = (it.get("tooltip") or "")
        des, exp = _parse_warning_range(tooltip)
        found.append((level, tooltip or label, des, exp))

    # Always delete prior rows so removals propagate even when no
    # current warnings are flagged.
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


# ─────────────────────────────────────────────────────────────────────
# 배당 (Naver finance.annual)
# ─────────────────────────────────────────────────────────────────────

def _ingest_dividend_for_ticker(ticker: str) -> int:
    """Pull 주당배당금 (DPS) from Naver finance.annual, compute yield
    against the latest weekly close stored in `bars`. Skip when no DPS
    or no price.
    """
    code = ticker.split(".")[0]
    payload = _naver_get(_FINANCE_ANNUAL_URL.format(code=code))
    if payload is None:
        return 0
    finance = payload.get("financeInfo") or {}
    rows = finance.get("rowList") or []
    title_list = finance.get("trTitleList") or []
    # Find the latest non-consensus column key.
    latest_actual_key: Optional[str] = None
    for t in reversed(title_list):
        if t.get("isConsensus") == "N":
            latest_actual_key = t.get("key")
            break
    if not latest_actual_key:
        return 0

    dps: Optional[float] = None
    for row in rows:
        if row.get("title") == "주당배당금":
            cols = row.get("columns") or {}
            cell = cols.get(latest_actual_key)
            if isinstance(cell, dict):
                v = cell.get("value")
                if v not in (None, "", "-"):
                    try:
                        dps = float(str(v).replace(",", ""))
                    except (TypeError, ValueError):
                        dps = None
            break
    if dps is None or dps <= 0:
        # Company doesn't pay dividend; clear stale row if exists then skip.
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM dividend_info WHERE ticker = %s",
                            (ticker,))
        return 0

    # Compute yield = DPS / latest close. Pull latest weekly close.
    yield_pct: Optional[float] = None
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT close FROM bars WHERE ticker = %s AND granularity = 'W' "
                "ORDER BY bar_date DESC LIMIT 1",
                (ticker,),
            )
            row = cur.fetchone()
    if row and row[0] is not None:
        try:
            close = float(row[0])
            if close > 0:
                yield_pct = (dps / close) * 100
        except (TypeError, ValueError):
            pass

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
                (ticker, dps, yield_pct),
            )
    return 1


# ─────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────

def run_all(
    tickers: Optional[Iterable[str]] = None,
    do_warnings: bool = True,
    do_dividends: bool = True,
    sleep_between: float = 0.08,
) -> dict:
    if tickers is None:
        tickers = _engagement_kr_tickers()
    tickers = list(tickers)
    log.info("ingest_market_signals: %d tickers (Naver-only)", len(tickers))

    counts = {"warnings": 0, "dividends": 0, "errors": 0}
    for i, t in enumerate(tickers, 1):
        try:
            if do_warnings:
                counts["warnings"] += _ingest_warnings_for_ticker(t)
            if do_dividends:
                counts["dividends"] += _ingest_dividend_for_ticker(t)
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
    p.add_argument("--warnings-only", action="store_true")
    p.add_argument("--dividends-only", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    do_w = not args.dividends_only
    do_d = not args.warnings_only
    run_all(tickers=args.tickers, do_warnings=do_w, do_dividends=do_d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
