"""Detect new DART disclosures on watchlisted tickers → push to Telegram.

Pipeline (runs as a daily-scan step):

  1. Build union of all users' watchlists (KR tickers only — DART scope).
  2. For each watchlist ticker, fetch last 24-hour DART filings via
     `app.db.ingest_news.fetch_dart_disclosures(days_back=2)`.  Upsert
     into `disclosures`.
  3. For each (user, ticker, rcept_no) NOT YET in
     `disclosure_alert_seen` AND with the user's
     `alert_preferences.enable_disclosure = true`, format + send a
     Telegram message, then insert into both `alerts` and
     `disclosure_alert_seen`.

Idempotent — re-running the script within minutes finds 0 new alerts
because every (user, rcept_no) is in `disclosure_alert_seen`. Two-PK
guard so the same disclosure can never alert the same user twice.

Why watchlist-only:
  - DART list API: 10K calls/day cap, ~30 watchlist tickers per active
    user. Even with 100 active users × 30 unique = 3K tickers; well
    under cap. Whole pipeline runs in under 4 minutes per pass.
  - Full universe (~2,700) is already covered by the WEEKLY
    fundamentals cron. Daily is just for the engagement set —
    matching the bars/scan engagement-set pattern site-wide.

usage:
    python -m app.db.notify_disclosure_alerts
    python -m app.db.notify_disclosure_alerts --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn  # noqa: E402
from app.db.ingest_news import (  # noqa: E402
    fetch_dart_disclosures,
    upsert_disclosures,
)
from app.db.telegram_worker import send_telegram  # noqa: E402

log = logging.getLogger("notify_disclosure_alerts")


def _watchers_by_ticker() -> Dict[str, List[Tuple[str, str, str]]]:
    """Returns {ticker: [(user_id, telegram_chat_id, name)]} —
    only users whose alert_preferences.enable_disclosure = true
    AND bedrest_mode = false AND telegram_chat_id is set.

    bedrest_mode (회고 #3) — 책 정신상 와병투자 모드 ON 사용자는
    모든 즉시 알림 OFF. disclosure 도 매일 발생 이벤트라 OFF 가
    일관성 맞음. weekly digest 가 대신 모아서 전달.
    """
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT w.ticker, u.id::text, u.telegram_chat_id, t.name
                  FROM watchlist w
                  JOIN users u ON u.id = w.user_id
                  JOIN alert_preferences ap ON ap.user_id = u.id
                  LEFT JOIN tickers t ON t.ticker = w.ticker
                 WHERE ap.enable_disclosure = true
                   AND COALESCE(ap.bedrest_mode, false) = false
                   AND u.telegram_chat_id IS NOT NULL
                   AND u.telegram_chat_id <> ''
                   AND (w.ticker LIKE '%.KS' OR w.ticker LIKE '%.KQ')
                """
            )
            out: Dict[str, List[Tuple[str, str, str]]] = {}
            for ticker, uid, chat_id, name in cur.fetchall():
                out.setdefault(ticker, []).append(
                    (uid, chat_id or "", name or ticker)
                )
            return out


def _disclosure_meta(ticker: str, rcept_no: str) -> Optional[Dict[str, str]]:
    """Look up the just-upserted disclosure row for message formatting."""
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT report_nm, filed_date, url FROM disclosures "
                "WHERE rcept_no = %s LIMIT 1",
                (rcept_no,),
            )
            r = cur.fetchone()
            if not r:
                return None
            return {"report_nm": r[0] or "", "filed_date": str(r[1] or ""),
                    "url": r[2] or ""}


def _already_seen(user_id: str, rcept_no: str) -> bool:
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM disclosure_alert_seen "
                "WHERE user_id = %s AND rcept_no = %s LIMIT 1",
                (user_id, rcept_no),
            )
            return cur.fetchone() is not None


def _mark_seen(user_id: str, rcept_no: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO disclosure_alert_seen (user_id, rcept_no) "
                "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (user_id, rcept_no),
            )


def _insert_alert(user_id: str, ticker: str, message: str, sent: bool) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alerts (user_id, ticker, alert_type, message,
                                    severity, sent_telegram, sent_at)
                VALUES (%s, %s, 'disclosure', %s, 'info', %s,
                        CASE WHEN %s THEN now() ELSE NULL END)
                """,
                (user_id, ticker, message, sent, sent),
            )


def format_disclosure_message(name: str, ticker: str, report_nm: str,
                              filed_date: str, url: str) -> str:
    """Telegram HTML — short + action-oriented + clickable link.

    Tone: "이 종목에 OO 공시 떴음 → 이런 의미 → 확인하러 가기".
    """
    # Pattern-based hint for high-signal report names so the user
    # immediately knows whether to drop what they're doing.
    rn = report_nm or ""
    hint = ""
    if any(k in rn for k in ("자기주식", "자사주매입", "자사주 취득")):
        hint = "💰 자사주 매입 — 주가 부양 + 회사가 저평가 본다는 신호."
    elif "유상증자" in rn:
        hint = "⚠️ 유상증자 — 단기 희석 가능. 발행가 vs 현재가 확인 필수."
    elif "전환사채" in rn or "CB" in rn:
        hint = "⚠️ 전환사채 발행 — 향후 희석 위험. 발행조건 검토."
    elif any(k in rn for k in ("배당", "현금배당")):
        hint = "💵 배당 관련 공시 — 권리락일 / 배당락일 체크."
    elif "사업보고서" in rn or "분기보고서" in rn or "반기보고서" in rn:
        hint = "📊 정기 실적 공시 — 컨센서스 대비 surprise 여부 확인."
    elif "최대주주" in rn or "5%" in rn or "대량보유" in rn:
        hint = "🐳 지분 변동 공시 — 큰손이 사고/팔고 있는지 확인."
    elif "공정공시" in rn:
        hint = "📣 공정공시 — 실적 가이던스 / IR 관련. 즉시 확인."
    else:
        hint = "📋 일반 공시 — 내용 확인 후 보유 의사결정 조정."

    name_disp = name or ticker
    return (
        f"📢 <b>{name_disp}</b> ({ticker}) 새 공시\n"
        f"<b>{rn}</b>\n"
        f"📅 접수: {filed_date}\n\n"
        f"{hint}\n\n"
        f'<a href="{url}">DART 공시 원문 보기 ↗</a>'
    )


def process_one_ticker(
    ticker: str,
    watchers: List[Tuple[str, str, str]],
    days_back: int,
    dry_run: bool,
) -> int:
    """Returns # alerts dispatched for this ticker."""
    code = ticker.split(".")[0]
    items = fetch_dart_disclosures(code, days_back=days_back)
    if not items:
        return 0
    # Upsert first (idempotent — `ON CONFLICT (rcept_no) DO NOTHING`).
    upsert_disclosures(ticker, items)

    dispatched = 0
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    for it in items:
        rcept = it.get("rcept_no")
        if not rcept:
            continue
        meta = _disclosure_meta(ticker, rcept) or {
            "report_nm": it.get("report_nm", ""),
            "filed_date": it.get("filed_date", "") or "",
            "url": it.get("url", ""),
        }
        for user_id, chat_id, name in watchers:
            if _already_seen(user_id, rcept):
                continue
            message = format_disclosure_message(
                name, ticker, meta["report_nm"], meta["filed_date"], meta["url"]
            )
            sent = False
            if not dry_run and chat_id and token:
                try:
                    sent = send_telegram(chat_id, message, token=token)
                except Exception as e:
                    log.warning("telegram send failed user=%s ticker=%s: %s",
                                user_id, ticker, e)
                    sent = False
            if not dry_run:
                _insert_alert(user_id, ticker, message, sent)
                _mark_seen(user_id, rcept)
            dispatched += 1
            log.info("[%s] %s → user=%s rcept=%s sent=%s",
                     ticker, meta["report_nm"][:40], user_id[:8], rcept, sent)
    return dispatched


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="Don't send Telegram or insert rows.")
    p.add_argument("--days-back", type=int, default=2,
                   help="DART list window. Default 2 covers 24h with margin.")
    p.add_argument("--sleep", type=float, default=0.08,
                   help="Per-ticker delay — DART 1000 req/min cap.")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    by_ticker = _watchers_by_ticker()
    log.info("disclosure-alert sweep — %d watchlisted KR tickers across users",
             len(by_ticker))
    total = 0
    for i, (ticker, watchers) in enumerate(by_ticker.items(), 1):
        try:
            total += process_one_ticker(ticker, watchers, args.days_back, args.dry_run)
        except Exception as e:
            log.warning("ticker=%s sweep error: %s", ticker, e)
        if i % 50 == 0:
            log.info("  progress: %d/%d alerts=%d", i, len(by_ticker), total)
        time.sleep(args.sleep)
    log.info("done — %d alerts dispatched (dry_run=%s)", total, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
