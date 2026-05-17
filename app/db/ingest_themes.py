"""KR theme ingest: Naver Finance theme list → Supabase.

Naver Finance (finance.naver.com/sise/theme.naver) exposes ~150 Korean
themes with daily change %, leading + lagging tickers, and member counts.
We scrape this every day and store a snapshot.

(finup.co.kr is Phase 1's preferred source per the book but their public
page is a Next.js SPA that doesn't render server-side; switching to
Naver as the data backbone is more robust and book's "topdown 3단계"
analysis works identically — themes show what's hot.)

Schema (themes table is added in migration 006):
    themes:     theme_id PK, name, members, updated_at
    theme_daily: theme_id, day, change_pct_1d, change_pct_1m, leading_ticker,
                 leading_name, lagging_ticker, lagging_name
    theme_members: theme_id, ticker  (many-to-many)

Usage:
    python -m app.db.ingest_themes
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402

log = logging.getLogger("ingest_themes")

NAVER_THEME_LIST = "https://finance.naver.com/sise/theme.naver?page={page}"
NAVER_THEME_DETAIL = "https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no={no}"

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (research)"})


# ----------------------------------------------------------------------------
# List page → [(theme_id, name, change_1d_pct, change_1m_pct, members,
#               up, down, flat, leading_ticker, leading_name,
#               lagging_ticker, lagging_name)]
# ----------------------------------------------------------------------------

# Naver theme list page has irregular row markup; parse in stages instead
# of one mega-regex.
_THEME_LINK_RE = re.compile(
    r'<a\s+href="/sise/sise_group_detail\.naver\?type=theme&no=(\d+)"[^>]*>([^<]+)</a>',
)
_TR_SPLIT_RE = re.compile(r'<tr[^>]*>')


def fetch_theme_page(page: int = 1) -> List[Dict[str, Any]]:
    r = _SESSION.get(NAVER_THEME_LIST.format(page=page), timeout=15)
    r.raise_for_status()
    rows: List[Dict[str, Any]] = []
    # Split into rows; each <tr> with a theme link is one theme.
    for chunk in _TR_SPLIT_RE.split(r.text):
        link = _THEME_LINK_RE.search(chunk)
        if not link:
            continue
        theme_id = int(link.group(1))
        name = link.group(2).strip()
        # Extract all "+1.23%" or "-1.23%" numbers in order
        pcts = re.findall(r'([+\-][\d.]+)%', chunk)
        # Extract member count and up/down/flat (4 col_type4 cells)
        nums = re.findall(r'col_type4">(\d+)</td>', chunk)
        # Extract leading/lagging tickers (item/main?code=NNNNNN)
        items = re.findall(r'/item/main\.naver\?code=(\d{6})"[^>]*>([^<]+)</a>', chunk)
        if not pcts:
            continue
        change_1d = float(pcts[0])
        change_1m = float(pcts[1]) if len(pcts) > 1 else None
        members = int(nums[0]) if nums else 0
        leading = items[0] if items else (None, None)
        lagging = items[1] if len(items) > 1 else (None, None)
        rows.append({
            "theme_id":     theme_id,
            "name":         name,
            "change_1d":    change_1d,
            "change_1m":    change_1m,
            "members":      members,
            "leading_code": leading[0],
            "leading_name": (leading[1] or "").strip() if leading[1] else None,
            "lagging_code": lagging[0],
            "lagging_name": (lagging[1] or "").strip() if lagging[1] else None,
        })
    return rows


def fetch_all_themes(max_pages: int = 8) -> List[Dict[str, Any]]:
    seen: Dict[int, Dict[str, Any]] = {}
    for page in range(1, max_pages + 1):
        rows = fetch_theme_page(page)
        if not rows:
            break
        for r in rows:
            seen[r["theme_id"]] = r
        log.info("  page %d: %d themes", page, len(rows))
        time.sleep(0.5)
    return list(seen.values())


# ----------------------------------------------------------------------------
# Theme detail → constituent tickers
# ----------------------------------------------------------------------------

_DETAIL_MEMBER_RE = re.compile(
    r'<a\s+href="/item/main\.naver\?code=(\d{6})"[^>]*>([^<]+)</a>',
)


def fetch_theme_members(theme_id: int) -> List[Tuple[str, str]]:
    """Returns [(stock_code, name)] for the theme. Naver caps at ~30 visible
    members on the first page; we follow pagination if present."""
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


# ----------------------------------------------------------------------------
# Persistence
# ----------------------------------------------------------------------------

def _ticker_for(stock_code: str) -> Optional[str]:
    """Resolve a 6-digit code to .KS or .KQ ticker using the tickers master."""
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ticker FROM tickers WHERE ticker IN (%s, %s) LIMIT 1",
                (f"{stock_code}.KS", f"{stock_code}.KQ"),
            )
            r = cur.fetchone()
            return r[0] if r else None


def upsert_themes(themes: List[Dict[str, Any]]) -> int:
    if not themes:
        return 0
    today = date.today()
    with get_conn() as conn:
        with conn.cursor() as cur:
            for t in themes:
                cur.execute(
                    """
                    INSERT INTO themes (theme_id, name, members, updated_at)
                    VALUES (%s, %s, %s, now())
                    ON CONFLICT (theme_id) DO UPDATE SET
                      name = EXCLUDED.name, members = EXCLUDED.members,
                      updated_at = now()
                    """,
                    (t["theme_id"], t["name"], t["members"]),
                )
            # Daily snapshot — one row per theme per day
            rows = [
                (t["theme_id"], today, t["change_1d"], t["change_1m"],
                 _ticker_for(t["leading_code"]) if t.get("leading_code") else None,
                 t["leading_name"],
                 _ticker_for(t["lagging_code"]) if t.get("lagging_code") else None,
                 t["lagging_name"])
                for t in themes
            ]
            cur.executemany(
                """
                INSERT INTO theme_daily
                  (theme_id, day, change_pct_1d, change_pct_1m,
                   leading_ticker, leading_name, lagging_ticker, lagging_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (theme_id, day) DO UPDATE SET
                  change_pct_1d = EXCLUDED.change_pct_1d,
                  change_pct_1m = EXCLUDED.change_pct_1m,
                  leading_ticker = EXCLUDED.leading_ticker,
                  leading_name = EXCLUDED.leading_name,
                  lagging_ticker = EXCLUDED.lagging_ticker,
                  lagging_name = EXCLUDED.lagging_name
                """,
                rows,
            )
    return len(themes)


def upsert_members(theme_id: int, members: List[Tuple[str, str]]) -> int:
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
            # Replace this theme's membership set
            cur.execute("DELETE FROM theme_members WHERE theme_id = %s",
                        (theme_id,))
            cur.executemany(
                "INSERT INTO theme_members (theme_id, ticker) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING",
                rows,
            )
    return len(rows)


# ----------------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--themes-only", action="store_true",
                   help="skip per-theme member fetch")
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
    log.info("themes + theme_daily upserted")

    if not args.themes_only:
        log.info("fetching members for %d themes...", len(themes))
        total_members = 0
        for i, t in enumerate(themes, 1):
            try:
                members = fetch_theme_members(t["theme_id"])
                total_members += upsert_members(t["theme_id"], members)
            except Exception as e:
                log.warning("members %s: %s", t["theme_id"], e)
            if i % 25 == 0:
                log.info("  %d/%d themes, %d total members",
                         i, len(themes), total_members)
        log.info("done: %d theme_member rows", total_members)
    return 0


if __name__ == "__main__":
    sys.exit(main())
