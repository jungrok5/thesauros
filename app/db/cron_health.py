"""Cron health check — alerts admin via Telegram when the daily-scan
hasn't refreshed the data the user-facing site depends on.

What "fresh" means here:
  - `analyze_results.updated_at` should have at least one KR row updated
    today (post-cutoff) on a weekday.
  - On weekends / pre-market, we don't alert — the most-recent weekday
    cycle is acceptable.

Why this exists — GitHub Actions occasionally skips a scheduled cron
(known issue on free runners; missed Mar/May/etc.). Without this, a
silently-missed day-scan means users see stale data until the next run.
The alert tells the admin to manually re-dispatch.

Schedule (see .github/workflows/cron-health-check.yml): runs at 10:00
UTC Mon-Fri, 2 hours after daily-scan's 08:00 UTC slot. Two hours is
ample headroom for a normal run (~25 min after the DART move) plus
GH Actions queue time.

Standalone:
    python -m app.db.cron_health             # check, alert if stale
    python -m app.db.cron_health --dry-run   # just log
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402

log = logging.getLogger("cron_health")

KST = timezone(timedelta(hours=9))


def expected_kr_cutoff(now_utc: Optional[datetime] = None) -> datetime:
    """The latest UTC timestamp after which we expect today's KR bars
    to be in Supabase. KR cron runs at 08:00 UTC = 17:00 KST and the
    pipeline takes ~25 min, so we use 08:30 UTC as the deadline. If
    `now` is before that on a weekday, the previous weekday's deadline
    is the reference (we shouldn't alert mid-cron).
    """
    now = now_utc or datetime.now(timezone.utc)
    today_deadline = now.replace(hour=8, minute=30, second=0, microsecond=0)
    weekday = now.weekday()  # 0=Mon..6=Sun
    is_weekday = weekday < 5

    if is_weekday and now >= today_deadline:
        return today_deadline
    # Step back to the most recent weekday's deadline.
    d = now.date()
    for _ in range(8):
        d = d - timedelta(days=1)
        if d.weekday() < 5:
            return datetime.combine(d, today_deadline.time(), tzinfo=timezone.utc)
    return today_deadline


def latest_kr_analyze_at() -> Optional[datetime]:
    """MAX(updated_at) across KR analyze_results rows. None if empty."""
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(updated_at) FROM analyze_results "
                "WHERE ticker LIKE '%.KS' OR ticker LIKE '%.KQ'"
            )
            row = cur.fetchone()
    return row[0] if row else None


def admin_chat_ids() -> List[str]:
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT telegram_chat_id FROM users "
                "WHERE role = 'admin' AND telegram_chat_id IS NOT NULL"
            )
            return [r[0] for r in cur.fetchall() if r[0]]


def send_telegram(chat_id: str, text: str) -> bool:
    """Bypass app.db.telegram_worker so we don't pull alert formatting
    overhead. Returns True on HTTP 200."""
    import requests
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        log.error("TELEGRAM_BOT_TOKEN missing — can't alert")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        return r.status_code == 200
    except requests.RequestException as e:
        log.error("telegram send failed: %s", e)
        return False


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="Just log the verdict, don't send Telegram")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    now = datetime.now(timezone.utc)
    deadline = expected_kr_cutoff(now)
    latest = latest_kr_analyze_at()

    log.info("now UTC: %s", now.isoformat())
    log.info("expected deadline: %s", deadline.isoformat())
    log.info("latest analyze_results: %s",
             latest.isoformat() if latest else "(none)")

    if latest and latest >= deadline:
        log.info("OK: data is fresh (latest >= deadline)")
        return 0

    # Stale — build alert.
    age_min = int((now - latest).total_seconds() / 60) if latest else -1
    age_label = f"{age_min // 60}h {age_min % 60}m" if age_min >= 0 else "n/a"
    kst_now = now.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")
    text = (
        "🚨 <b>Daily-scan stale</b>\n"
        f"now: {kst_now}\n"
        f"expected ≥ {deadline.astimezone(KST).strftime('%H:%M KST')}\n"
        f"latest analyze_results: "
        f"{latest.astimezone(KST).strftime('%Y-%m-%d %H:%M KST') if latest else 'never'}\n"
        f"age: {age_label}\n\n"
        "→ daily-scan didn't run or didn't finish. Manually dispatch:\n"
        "gh workflow run daily-scan.yml"
    )

    chat_ids = admin_chat_ids()
    if not chat_ids:
        log.warning("no admin chat_ids — cannot alert")
        return 2

    if args.dry_run:
        log.info("DRY-RUN: would alert %d admin(s)", len(chat_ids))
        log.info("message:\n%s", text)
        return 1

    sent = sum(send_telegram(c, text) for c in chat_ids)
    log.info("alerted %d/%d admins", sent, len(chat_ids))
    return 0 if sent > 0 else 3


if __name__ == "__main__":
    sys.exit(main())
