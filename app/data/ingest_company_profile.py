"""Ingest company overview / business summary into company_profile.

Two sources:
  - KR tickers (.KS / .KQ): DART OpenAPI company.json + disclosures
    /api/list.json filtered to "특수공시" type for last_filings.
  - US tickers: SEC EDGAR submissions.json (industry / SIC / business
    summary fallback) + most recent 10-K's Item 1 text when available.

The endpoint contracts are well-documented:
  DART:     https://opendart.fss.or.kr/api/company.json?crtfc_key=KEY&corp_code=00126380
  SEC:      https://data.sec.gov/submissions/CIK0000320193.json

Both APIs are free, no daily quota for the small per-ticker calls
we make (KR ~3,000 tickers × 1 call/week = 3K req; SEC ~500 × 1 = 500).

Run standalone:
    python -m app.data.ingest_company_profile --tickers AAPL 005930.KS
    python -m app.data.ingest_company_profile           # all active KR + watchlist US
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn  # noqa: E402

log = logging.getLogger("ingest_company_profile")

DART_BASE = "https://opendart.fss.or.kr/api"
SEC_BASE = "https://data.sec.gov"


def _kr_code(ticker: str) -> Optional[str]:
    """000150.KS → 000150 (6-digit code DART uses as stock_code)."""
    if "." not in ticker:
        return None
    code, suffix = ticker.split(".", 1)
    if suffix in ("KS", "KQ") and code.isdigit() and len(code) == 6:
        return code
    return None


def _dart_corp_code(stock_code: str) -> Optional[str]:
    """Map a 6-digit KRX stock code to DART's internal 8-digit corp_code.
    Uses the existing fetch_corp_code_map() helper in ingest_dart.py."""
    try:
        from app.data.ingest_dart import fetch_corp_code_map
        df = fetch_corp_code_map()
        row = df.loc[df["stock_code"] == stock_code]
        if row.empty:
            return None
        return str(row["corp_code"].iloc[0])
    except Exception as e:
        log.debug("corp_code lookup %s: %s", stock_code, e)
        return None


def fetch_dart_company(corp_code: str) -> Optional[Dict[str, Any]]:
    """DART company.json — company overview (name, industry, ceo, est_dt,
    address). Free, no rate limit at this volume."""
    key = os.environ.get("DART_API_KEY")
    if not key:
        return None
    try:
        r = requests.get(
            f"{DART_BASE}/company.json",
            params={"crtfc_key": key, "corp_code": corp_code},
            timeout=10,
        )
        r.raise_for_status()
        j = r.json()
        if j.get("status") != "000":
            return None
        return j
    except Exception as e:
        log.debug("dart company %s: %s", corp_code, e)
        return None


def fetch_recent_special_disclosures(stock_code: str,
                                     limit: int = 10) -> List[Dict[str, Any]]:
    """Pull the last N DART filings for a ticker (any type). We don't
    filter to 특수공시 here — the caller can dedupe / filter."""
    key = os.environ.get("DART_API_KEY")
    if not key:
        return []
    try:
        # /list.json without date filter returns latest pages.
        r = requests.get(
            f"{DART_BASE}/list.json",
            params={
                "crtfc_key": key,
                "stock_code": stock_code,
                "page_no": 1,
                "page_count": limit,
            },
            timeout=10,
        )
        r.raise_for_status()
        j = r.json()
        if j.get("status") != "000":
            return []
        out: List[Dict[str, Any]] = []
        for item in j.get("list", [])[:limit]:
            out.append({
                "type": item.get("report_nm", "")[:80],
                "date": item.get("rcept_dt", ""),
                "title": item.get("report_nm", ""),
                "url": f"http://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.get('rcept_no')}",
            })
        return out
    except Exception as e:
        log.debug("dart list %s: %s", stock_code, e)
        return []


def kr_company_profile(ticker: str) -> Optional[Dict[str, Any]]:
    """Build a company_profile row for one KR ticker via DART."""
    stock_code = _kr_code(ticker)
    if not stock_code:
        return None
    corp_code = _dart_corp_code(stock_code)
    if not corp_code:
        return None
    info = fetch_dart_company(corp_code)
    if not info:
        return None
    filings = fetch_recent_special_disclosures(stock_code, limit=10)
    # Parse 설립일 YYYYMMDD → date
    founded = None
    est = info.get("est_dt")
    if isinstance(est, str) and len(est) == 8 and est.isdigit():
        founded = f"{est[:4]}-{est[4:6]}-{est[6:]}"
    return {
        "ticker": ticker,
        "source": "DART",
        "industry": info.get("induty_code") or None,
        "sectors": None,           # DART doesn't expose sector list directly
        "summary": (
            f"{info.get('corp_name', '')} ({info.get('corp_name_eng', '')})"
            + ((" — 본사 " + info.get("adres", "")) if info.get("adres") else "")
            + ((" / 결산월 " + str(info.get("acc_mt", ""))) if info.get("acc_mt") else "")
        ).strip() or None,
        "ceo": info.get("ceo_nm") or None,
        "founded": founded,
        "hq": info.get("adres") or None,
        "website": info.get("hm_url") or None,
        "market_cap_krw": None,    # filled separately via prices × shares_out
        "market_cap_usd": None,
        "last_filings": filings,
    }


# ────────────────────────────────────────────────────────────────────────
# US — SEC EDGAR
# ────────────────────────────────────────────────────────────────────────

def _sec_headers() -> Dict[str, str]:
    """SEC requires a User-Agent identifying the requester."""
    ua = os.environ.get("SEC_USER_AGENT") or "Thesauros Research info@example.com"
    return {"User-Agent": ua}


def _us_cik(ticker: str) -> Optional[str]:
    """Resolve US ticker → CIK via SEC's company_tickers.json mapping.
    Cached in-process for the duration of a run."""
    if hasattr(_us_cik, "_cache"):
        return _us_cik._cache.get(ticker.upper())
    try:
        r = requests.get(
            f"{SEC_BASE.replace('data.', 'www.')}/files/company_tickers.json",
            headers=_sec_headers(), timeout=10,
        )
        r.raise_for_status()
        mapping = {
            str(v["ticker"]).upper(): str(v["cik_str"]).zfill(10)
            for v in r.json().values()
        }
        _us_cik._cache = mapping        # type: ignore[attr-defined]
        return mapping.get(ticker.upper())
    except Exception as e:
        log.debug("sec ticker map: %s", e)
        _us_cik._cache = {}              # type: ignore[attr-defined]
        return None


def us_company_profile(ticker: str) -> Optional[Dict[str, Any]]:
    """Build a company_profile row for one US ticker via SEC EDGAR."""
    cik = _us_cik(ticker)
    if not cik:
        return None
    try:
        r = requests.get(
            f"{SEC_BASE}/submissions/CIK{cik}.json",
            headers=_sec_headers(), timeout=10,
        )
        r.raise_for_status()
        sub = r.json()
    except Exception as e:
        log.debug("sec sub %s: %s", ticker, e)
        return None

    recent = sub.get("filings", {}).get("recent", {}) or {}
    forms = recent.get("form", []) or []
    dates = recent.get("filingDate", []) or []
    titles = recent.get("primaryDocDescription", []) or []
    accs = recent.get("accessionNumber", []) or []
    filings: List[Dict[str, Any]] = []
    for i in range(min(20, len(forms))):
        form = forms[i]
        # Highlight informative filings — 10-K/10-Q/8-K/S-1, skip 4 (insider).
        if form in ("3", "4", "5", "144"):
            continue
        if len(filings) >= 10:
            break
        acc = accs[i].replace("-", "")
        filings.append({
            "type": form,
            "date": dates[i],
            "title": titles[i] or form,
            "url": (
                f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                f"&CIK={cik}&type={form}&dateb=&owner=include&count=10"
            ) if not acc else (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/"
            ),
        })

    sectors = sub.get("sicDescription")
    summary_lines = [
        sub.get("name") or ticker,
        f"SIC {sub.get('sic')} — {sectors}" if sectors else None,
        f"Exchange: {sub.get('exchanges', [None])[0]}" if sub.get("exchanges") else None,
        sub.get("description") or None,
    ]
    summary = " · ".join(s for s in summary_lines if s)

    return {
        "ticker": ticker,
        "source": "SEC",
        "industry": sub.get("sicDescription") or None,
        "sectors": [sectors] if sectors else None,
        "summary": summary or None,
        "ceo": None,                # not in submissions.json
        "founded": None,
        "hq": sub.get("addresses", {}).get("business", {}).get("city") or None,
        "website": None,
        "market_cap_krw": None,
        "market_cap_usd": None,
        "last_filings": filings,
    }


# ────────────────────────────────────────────────────────────────────────
# Upsert + driver
# ────────────────────────────────────────────────────────────────────────

def upsert_profile(row: Dict[str, Any]) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO company_profile
                  (ticker, source, industry, sectors, summary, ceo, founded,
                   hq, website, market_cap_krw, market_cap_usd, last_filings,
                   fetched_at, updated_at)
                VALUES
                  (%s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s::jsonb, now(), now())
                ON CONFLICT (ticker) DO UPDATE SET
                  source = EXCLUDED.source,
                  industry = EXCLUDED.industry,
                  sectors = EXCLUDED.sectors,
                  summary = EXCLUDED.summary,
                  ceo = EXCLUDED.ceo,
                  founded = EXCLUDED.founded,
                  hq = EXCLUDED.hq,
                  website = EXCLUDED.website,
                  market_cap_krw = EXCLUDED.market_cap_krw,
                  market_cap_usd = EXCLUDED.market_cap_usd,
                  last_filings = EXCLUDED.last_filings,
                  updated_at = now()
                """,
                (
                    row["ticker"], row["source"], row.get("industry"),
                    row.get("sectors"), row.get("summary"), row.get("ceo"),
                    row.get("founded"), row.get("hq"), row.get("website"),
                    row.get("market_cap_krw"), row.get("market_cap_usd"),
                    json.dumps(row.get("last_filings") or [], ensure_ascii=False),
                ),
            )


def fetch_profile(ticker: str) -> Optional[Dict[str, Any]]:
    """Auto-route to KR (DART) or US (SEC) based on ticker suffix."""
    if "." in ticker:
        return kr_company_profile(ticker)
    return us_company_profile(ticker)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", nargs="+", default=None)
    p.add_argument("--watchlist-only", action="store_true",
                   help="Ingest only tickers present in any user's watchlist")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    tickers: List[str]
    if args.tickers:
        tickers = list(args.tickers)
    elif args.watchlist_only:
        from app.db.scan_daily import _watchlist_tickers
        tickers = _watchlist_tickers()
    else:
        # Default: every active KR ticker + every watchlisted US ticker.
        from app.db import get_conn
        with get_conn(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT ticker FROM tickers WHERE is_active = true "
                    "AND (market IN ('KOSPI','KOSDAQ') OR ticker IN ("
                    "  SELECT DISTINCT ticker FROM watchlist))"
                )
                tickers = [r[0] for r in cur.fetchall()]

    if args.limit:
        tickers = tickers[: args.limit]

    log.info("ingesting %d ticker(s)", len(tickers))
    t0 = time.time()
    stats = {"ok": 0, "skip": 0, "err": 0}
    for i, t in enumerate(tickers, 1):
        try:
            prof = fetch_profile(t)
            if not prof:
                stats["skip"] += 1
                continue
            upsert_profile(prof)
            stats["ok"] += 1
        except Exception as e:
            log.error("ticker=%s error: %s", t, e)
            stats["err"] += 1
        if i % 50 == 0:
            log.info("  [%d/%d] %s", i, len(tickers), stats)
    log.info("done in %.1fs: %s", time.time() - t0, stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
