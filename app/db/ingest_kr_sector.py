"""Ingest KR ticker → sector mapping from DART company.json.

DART's `induty_code` is the KSIC (Korea Standard Industrial Classification)
4-digit code. We map to a readable Korean sector label using KSIC_SECTOR_MAP
(top-level categories from KSIC 10th revision).

Performance:
  - DART rate limit: 1000 req/min → 60ms throttle minimum
  - ~3,000 KR tickers → ~3-5 minute full run
  - Concurrent fetch with ThreadPoolExecutor (max 8 workers stays under rate)
  - Batched UPDATE (executemany) → 1 round-trip per 500 rows

Usage:
    python -m app.db.ingest_kr_sector              # all KR tickers
    python -m app.db.ingest_kr_sector --tickers 005930.KS
    python -m app.db.ingest_kr_sector --limit 100  # smoke
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402

log = logging.getLogger("ingest_kr_sector")

DART_COMPANY = "https://opendart.fss.or.kr/api/company.json"

# KSIC 10차 개정 — 대분류 (A~U). induty_code 첫 자리수로 매핑.
# Reference: KOSIS 한국표준산업분류 (10차, 2017).
KSIC_TOP_LEVEL: Dict[str, str] = {
    "0": "농림어업", "1": "농림어업",
    "2": "광업·제조업",    "3": "제조업",
    "4": "유틸리티·건설·도소매",
    "5": "도소매·숙박·음식",
    "6": "정보통신·금융",
    "7": "전문·과학·관리",
    "8": "교육·보건·예술",
    "9": "기타 서비스",
}

# Fine-grained mapping by 3-digit KSIC prefix → human-friendly sector.
KSIC_3DIGIT: Dict[str, str] = {
    # 제조 (10~33)
    "10": "음식료품", "11": "음식료품", "12": "담배",
    "13": "섬유", "14": "의복·모피", "15": "가죽·신발",
    "16": "목재·종이", "17": "종이",
    "18": "인쇄·기록매체",
    "19": "코크스·석유정제",
    "20": "화학", "21": "의료용 물질·의약품", "22": "고무·플라스틱",
    "23": "비금속 광물제품",
    "24": "1차 금속",
    "25": "금속가공제품",
    "26": "전자부품·컴퓨터·통신장비",   # 반도체 = 264
    "27": "의료·정밀기기·광학기기",
    "28": "전기장비",
    "29": "기타 기계·장비",
    "30": "자동차·트레일러",
    "31": "기타 운송장비",   # 조선 등
    "32": "가구·기타",
    "33": "산업용 기계 수리",
    # 건설·전기·가스·수도 (35~42)
    "35": "전기·가스·증기",
    "36": "수도·하수·폐기물",
    "41": "종합건설", "42": "전문직별 공사",
    # 도소매·운수 (45~52)
    "45": "자동차 도소매", "46": "도매·중개", "47": "소매",
    "49": "육상 운송", "50": "수상 운송", "51": "항공 운송", "52": "창고·운송",
    # 숙박·음식 (55~56)
    "55": "숙박업", "56": "음식점·주점",
    # 정보통신 (58~63)
    "58": "출판",
    "59": "영상·오디오·방송",
    "60": "방송",
    "61": "통신",
    "62": "컴퓨터 프로그래밍·시스템",
    "63": "정보서비스",
    # 금융·보험 (64~66)
    "64": "금융", "65": "보험·연금", "66": "금융·보험 서비스",
    # 부동산 (68~69)
    "68": "부동산",
    # 전문·과학·기술 (70~73)
    "70": "연구개발",
    "71": "전문 서비스", "72": "건축·엔지니어링",
    "73": "기타 과학·기술",
    # 사업시설 (74~75)
    "74": "사업시설 관리", "75": "사업지원 서비스",
    # 공공·교육·보건 (84~87)
    "84": "공공행정",
    "85": "교육",
    "86": "보건업", "87": "사회복지",
    # 예술·스포츠·기타 (90~94)
    "90": "예술·스포츠", "91": "스포츠·오락",
    "92": "기타 개인서비스",
}


def sector_name(induty_code: str) -> Optional[str]:
    """induty_code → readable sector.

    KSIC codes vary in length (2~5 digits). We take the leading 2-digit
    sector prefix as-is — DO NOT zero-pad (that would turn '264' into
    '0264' and map to the wrong sector).
    """
    if not induty_code:
        return None
    code = str(induty_code).strip().lstrip("0") or "0"
    pref2 = code[:2]
    if pref2 in KSIC_3DIGIT:
        return KSIC_3DIGIT[pref2]
    pref1 = code[:1]
    return KSIC_TOP_LEVEL.get(pref1)


# ---------- DART corp_code map -------------------------------------------

_corp_map_cache: Optional[Dict[str, str]] = None
_corp_map_lock = Lock()


def _load_corp_map() -> Dict[str, str]:
    """{stock_code (6-digit): corp_code (8-digit)}. Lazy + thread-safe."""
    global _corp_map_cache
    if _corp_map_cache is not None:
        return _corp_map_cache
    with _corp_map_lock:
        if _corp_map_cache is not None:
            return _corp_map_cache
        try:
            from app.data.ingest_dart import fetch_corp_code_map
            df = fetch_corp_code_map()
        except Exception as e:
            log.error("corp_code map load failed: %s", e)
            _corp_map_cache = {}
            return _corp_map_cache
        m: Dict[str, str] = {}
        for _, row in df.iterrows():
            sc = str(row.get("stock_code", "")).strip()
            cc = str(row.get("corp_code", "")).strip()
            if sc and cc and sc.isdigit() and len(sc) == 6:
                m[sc] = cc
        _corp_map_cache = m
    log.info("corp_code map: %d entries", len(_corp_map_cache))
    return _corp_map_cache


_session = requests.Session()


def fetch_one(stock_code: str, api_key: str) -> Tuple[Optional[str], Optional[str]]:
    """Returns (induty_code, sector_name) or (None, None)."""
    corp_codes = _load_corp_map()
    cc = corp_codes.get(stock_code)
    if not cc:
        return None, None
    try:
        r = _session.get(DART_COMPANY,
                         params={"crtfc_key": api_key, "corp_code": cc},
                         timeout=8)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.debug("dart company %s: %s", stock_code, e)
        return None, None
    if data.get("status") != "000":
        return None, None
    induty = (data.get("induty_code") or "").strip()
    return induty or None, sector_name(induty)


# ---------- Driver --------------------------------------------------------

def _kr_tickers(limit: Optional[int], missing_only: bool) -> List[Tuple[str, str]]:
    """Returns [(ticker, stock_code)] for KR tickers."""
    where = "is_active = true AND market IN ('KOSPI', 'KOSDAQ')"
    if missing_only:
        where += " AND sector IS NULL"
    sql = f"SELECT ticker FROM tickers WHERE {where} ORDER BY ticker"
    if limit:
        sql += f" LIMIT {int(limit)}"
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return [(r[0], r[0].split(".")[0]) for r in cur.fetchall()]


def _flush_updates(rows: List[Tuple[str, Optional[str], Optional[str]]]) -> None:
    """Batched UPDATE — one connection, one round-trip."""
    if not rows:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE tickers SET sector = %s, industry = %s, updated_at = now() "
                "WHERE ticker = %s",
                # arg order: (sector, industry, ticker)
                [(s, i, t) for t, i, s in rows],
            )


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", nargs="+", default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--workers", type=int, default=8,
                   help="concurrent DART fetches (rate cap = 1000/min)")
    p.add_argument("--missing-only", action="store_true",
                   help="only fill rows where sector IS NULL")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    api_key = os.environ.get("DART_API_KEY")
    if not api_key:
        log.error("DART_API_KEY not set")
        return 1

    if args.tickers:
        targets = [(t, t.split(".")[0]) for t in args.tickers]
    else:
        targets = _kr_tickers(args.limit, args.missing_only)
    log.info("fetching sectors for %d tickers (workers=%d)", len(targets), args.workers)

    t0 = time.time()
    n_ok = n_skipped = 0
    BATCH = 250
    buffer: List[Tuple[str, Optional[str], Optional[str]]] = []

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        future_map = {
            ex.submit(fetch_one, code, api_key): (ticker, code)
            for ticker, code in targets
        }
        for done in as_completed(future_map):
            ticker, code = future_map[done]
            try:
                induty, sector = done.result()
            except Exception as e:
                log.debug("worker %s: %s", ticker, e)
                n_skipped += 1
                continue
            if sector is None:
                n_skipped += 1
                continue
            buffer.append((ticker, induty, sector))
            n_ok += 1
            if len(buffer) >= BATCH:
                _flush_updates(buffer)
                buffer.clear()
                log.info("  flushed %d (total ok=%d skipped=%d, elapsed=%.0fs)",
                         BATCH, n_ok, n_skipped, time.time() - t0)
    _flush_updates(buffer)
    log.info("done in %.1fs: ok=%d skipped=%d",
             time.time() - t0, n_ok, n_skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
