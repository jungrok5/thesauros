"""KR theme ingest: Naver Finance theme list → Supabase.

옛 구현 (c3fa5f1) 복원 — 2026-05-19 search-only pivot 시 drop 됐다가
2026-05-20 부활. **차이점:** 추천/점수/시계열 제거 (theme_daily 폐기).
themes + theme_members 만 적재. UI 가 우리 DB 의 analyze_results /
factors_eval 으로 종목 정보 표시 (테마 자체엔 점수 없음).

Naver Finance (finance.naver.com/sise/theme.naver) 가 ~265 개 한국
테마 + 종목 list 제공. 매주 1회 (weekly cron) 동기화.

usage:
    python -m app.db.ingest_themes
    python -m app.db.ingest_themes --themes-only  # member fetch skip
    python -m app.db.ingest_themes --max-pages 4  # debug
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn  # noqa: E402

log = logging.getLogger("ingest_themes")

NAVER_THEME_LIST = "https://finance.naver.com/sise/theme.naver?page={page}"
NAVER_THEME_DETAIL = "https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no={no}"

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (research)"})


# ─────────────────────────────────────────────────────────────────────
# List page parsing
# ─────────────────────────────────────────────────────────────────────

_THEME_LINK_RE = re.compile(
    r'<a\s+href="/sise/sise_group_detail\.naver\?type=theme&no=(\d+)"[^>]*>([^<]+)</a>',
)
_TR_SPLIT_RE = re.compile(r'<tr[^>]*>')


def fetch_theme_page(page: int = 1) -> List[Dict[str, Any]]:
    """단일 page (~50 themes) 에서 (theme_id, name, members) 추출."""
    r = _SESSION.get(NAVER_THEME_LIST.format(page=page), timeout=15)
    r.raise_for_status()
    rows: List[Dict[str, Any]] = []
    for chunk in _TR_SPLIT_RE.split(r.text):
        link = _THEME_LINK_RE.search(chunk)
        if not link:
            continue
        theme_id = int(link.group(1))
        name = link.group(2).strip()
        # 종목수 (members) — col_type4 cells 의 첫 번째
        nums = re.findall(r'col_type4">(\d+)</td>', chunk)
        members = int(nums[0]) if nums else 0
        rows.append({
            "theme_id": theme_id,
            "name": name,
            "members": members,
        })
    return rows


def fetch_all_themes(max_pages: int = 8) -> List[Dict[str, Any]]:
    """모든 page (1-8) 의 themes 통합. 중복 제거."""
    seen: Dict[int, Dict[str, Any]] = {}
    for page in range(1, max_pages + 1):
        try:
            rows = fetch_theme_page(page)
        except Exception as e:
            log.warning("page %d failed: %s", page, e)
            continue
        if not rows:
            break
        for r in rows:
            seen[r["theme_id"]] = r
        log.info("  page %d: %d themes", page, len(rows))
        time.sleep(0.5)
    return list(seen.values())


# ─────────────────────────────────────────────────────────────────────
# Detail page parsing — theme 별 종목 list
# ─────────────────────────────────────────────────────────────────────

_DETAIL_MEMBER_RE = re.compile(
    r'<a\s+href="/item/main\.naver\?code=(\d{6})"[^>]*>([^<]+)</a>',
)


def fetch_theme_members(theme_id: int) -> List[Tuple[str, str]]:
    """단일 테마의 종목 list (stock_code, name). pagination 따라감."""
    seen: Dict[str, str] = {}
    page = 1
    while page <= 5:
        url = NAVER_THEME_DETAIL.format(no=theme_id) + f"&page={page}"
        try:
            r = _SESSION.get(url, timeout=10)
            r.raise_for_status()
        except Exception:
            break
        new_count = 0
        for m in _DETAIL_MEMBER_RE.finditer(r.text):
            code, name = m.group(1), m.group(2).strip()
            if code not in seen:
                seen[code] = name
                new_count += 1
        if new_count == 0:
            break
        page += 1
        time.sleep(0.3)
    return list(seen.items())


# ─────────────────────────────────────────────────────────────────────
# Ticker resolution + upsert
# ─────────────────────────────────────────────────────────────────────

def _ticker_for(stock_code: str) -> Optional[str]:
    """6-digit code → .KS or .KQ suffix via tickers master."""
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ticker FROM tickers WHERE ticker IN (%s, %s) LIMIT 1",
                (f"{stock_code}.KS", f"{stock_code}.KQ"),
            )
            r = cur.fetchone()
            return r[0] if r else None


def upsert_themes(themes: List[Dict[str, Any]]) -> int:
    """themes 테이블 upsert. 점수/시계열 컬럼 없음."""
    if not themes:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO themes (theme_id, name, members, updated_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (theme_id) DO UPDATE SET
                  name = EXCLUDED.name,
                  members = EXCLUDED.members,
                  updated_at = now()
                """,
                [(t["theme_id"], t["name"], t["members"]) for t in themes],
            )
    return len(themes)


def upsert_members(theme_id: int, members: List[Tuple[str, str]]) -> int:
    """단일 테마의 member 종목 list 통째 replace."""
    if not members:
        return 0
    rows: List[Tuple[int, str]] = []
    for code, _name in members:
        t = _ticker_for(code)
        if t:
            rows.append((theme_id, t))
    if not rows:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM theme_members WHERE theme_id = %s",
                        (theme_id,))
            cur.executemany(
                "INSERT INTO theme_members (theme_id, ticker) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING",
                rows,
            )
    return len(rows)


# ─────────────────────────────────────────────────────────────────────
# Driver
# ─────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--themes-only", action="store_true",
                   help="skip per-theme member fetch (faster, no종목 update)")
    p.add_argument("--max-pages", type=int, default=8)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    log.info("fetching theme list...")
    themes = fetch_all_themes(max_pages=args.max_pages)
    log.info("got %d themes", len(themes))
    upsert_themes(themes)
    log.info("themes upserted")

    if not args.themes_only:
        log.info("fetching members for %d themes...", len(themes))
        total_members = 0
        for i, t in enumerate(themes, 1):
            try:
                members = fetch_theme_members(t["theme_id"])
                total_members += upsert_members(t["theme_id"], members)
            except Exception as e:
                log.warning("members %s: %s", t["theme_id"], e)
            if i % 50 == 0:
                log.info("  %d/%d themes, %d total members",
                         i, len(themes), total_members)
        log.info("done: %d theme_member rows total", total_members)
    return 0


if __name__ == "__main__":
    sys.exit(main())
