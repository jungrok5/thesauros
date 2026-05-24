"""Detect SL=10% breach on user-held positions → Telegram alert.

Pipeline (runs as a weekly cron step, after weekly bar close):

  1. Build (user, ticker, entry_price) for every watchlist row where
     category = 'holding' AND alerts_enabled = true.
  2. For each holding, read the latest WEEKLY close from `bars`.
  3. If (close - entry) / entry <= -SL_THRESHOLD_PCT → SL breach.
  4. Dedup against `stop_loss_alert_seen` on (user, ticker, bar_date)
     so we never alert the same user about the same week twice.
  5. Insert alert + send Telegram.

Idempotent — re-running within the same week is a no-op.

Per Sprint 1 backtest: SL=10% / max=8 / 24w hold = production winner.
This script implements the SL part for live holdings.

usage:
    python -m app.db.notify_stop_loss
    python -m app.db.notify_stop_loss --dry-run
    python -m app.db.notify_stop_loss --threshold 5    # tighter alert
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn                            # noqa: E402
from app.db.telegram_worker import send_telegram       # noqa: E402

log = logging.getLogger("notify_stop_loss")

SL_THRESHOLD_PCT_DEFAULT = 10.0


def _holdings() -> List[Tuple[str, str, str, float, str]]:
    """Returns [(user_id, ticker, name, entry_price, telegram_chat_id), ...]
    for every alert-enabled holding with a chat_id set."""
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.id::text, w.ticker, t.name, w.entry_price,
                       u.telegram_chat_id
                  FROM watchlist w
                  JOIN users u ON u.id = w.user_id
                  JOIN tickers t ON t.ticker = w.ticker
                 WHERE w.category = 'holding'
                   AND w.alerts_enabled = true
                   AND w.entry_price IS NOT NULL
                   AND w.entry_price > 0
                   AND u.telegram_chat_id IS NOT NULL
                   AND u.telegram_chat_id <> ''
                """
            )
            return [
                (r[0], r[1], r[2] or r[1], float(r[3]), r[4])
                for r in cur.fetchall()
            ]


def _latest_weekly_close(ticker: str) -> Optional[Tuple[float, str]]:
    """Returns (close, bar_date_iso) for the most recent weekly bar."""
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT close, bar_date FROM bars "
                "WHERE ticker = %s AND granularity = 'W' "
                "ORDER BY bar_date DESC LIMIT 1",
                (ticker,),
            )
            r = cur.fetchone()
            if not r or r[0] is None:
                return None
            return float(r[0]), str(r[1])


def _already_seen(user_id: str, ticker: str, bar_date: str) -> bool:
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM stop_loss_alert_seen "
                "WHERE user_id = %s AND ticker = %s "
                "  AND alerted_at_bar_date = %s LIMIT 1",
                (user_id, ticker, bar_date),
            )
            return cur.fetchone() is not None


def _mark_seen(
    user_id: str, ticker: str, bar_date: str,
    entry_price: float, close: float, drop_pct: float, sent: bool,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO stop_loss_alert_seen
                    (user_id, ticker, alerted_at_bar_date,
                     entry_price, bar_close_price, drop_pct, sent_telegram)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, ticker, alerted_at_bar_date)
                DO UPDATE SET sent_telegram = EXCLUDED.sent_telegram
                """,
                (user_id, ticker, bar_date, entry_price, close,
                 drop_pct, sent),
            )


def _insert_alert(user_id: str, ticker: str, message: str, sent: bool) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alerts (user_id, ticker, alert_type, message,
                                    severity, sent_telegram, sent_at)
                VALUES (%s, %s, 'stop_loss', %s, 'warn', %s,
                        CASE WHEN %s THEN now() ELSE NULL END)
                """,
                (user_id, ticker, message, sent, sent),
            )


def format_sl_message(
    name: str, ticker: str, entry_price: float, close: float,
    drop_pct: float, threshold: float,
) -> str:
    """Telegram HTML — 손절 신호 메시지."""
    return (
        f"🔻 <b>{name}</b> ({ticker}) 손절 신호\n"
        f"진입가: <code>{entry_price:,.0f}</code>\n"
        f"이번 주봉 종가: <code>{close:,.0f}</code>\n"
        f"<b>변동: {drop_pct:+.2f}%</b> (임계: -{threshold:.0f}%)\n\n"
        f"📕 책 정신: 손절은 빠르게, 회복 기대로 보유 연장은 추세 깨졌을 때 "
        f"가장 큰 손실 키움. 17년 backtest 검증 = SL 적용 시 +6380% "
        f"(no-SL +1047%).\n\n"
        f"의사결정: <a href=\"https://thesauros.vercel.app/stocks/{ticker}\">{ticker} 분석 ↗</a>"
    )


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true",
                   help="Don't send Telegram or insert rows.")
    p.add_argument("--threshold", type=float, default=SL_THRESHOLD_PCT_DEFAULT,
                   help="Drop pct that triggers alert. Default 10.0.")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    holdings = _holdings()
    log.info("loaded %d alert-enabled holdings", len(holdings))
    if not holdings:
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token and not args.dry_run:
        log.warning("TELEGRAM_BOT_TOKEN missing — running effectively dry")

    dispatched = 0
    skipped_seen = 0
    skipped_no_bar = 0
    above_threshold = 0
    for user_id, ticker, name, entry_price, chat_id in holdings:
        latest = _latest_weekly_close(ticker)
        if not latest:
            skipped_no_bar += 1
            continue
        close, bar_date = latest
        drop_pct = (close - entry_price) / entry_price * 100.0
        if drop_pct > -args.threshold:
            above_threshold += 1
            continue
        if _already_seen(user_id, ticker, bar_date):
            skipped_seen += 1
            continue
        message = format_sl_message(
            name, ticker, entry_price, close, drop_pct, args.threshold,
        )
        sent = False
        if not args.dry_run and chat_id and token:
            try:
                sent = send_telegram(chat_id, message, token=token)
            except Exception as e:
                log.warning("telegram send failed user=%s ticker=%s: %s",
                            user_id, ticker, e)
                sent = False
        if not args.dry_run:
            _insert_alert(user_id, ticker, message, sent)
            _mark_seen(user_id, ticker, bar_date, entry_price, close,
                       drop_pct, sent)
        dispatched += 1
        log.info(
            "[SL] user=%s ticker=%s entry=%.0f close=%.0f drop=%.2f%% sent=%s",
            user_id[:8], ticker, entry_price, close, drop_pct, sent,
        )

    log.info(
        "summary: dispatched=%d above_threshold=%d already_seen=%d no_bar=%d",
        dispatched, above_threshold, skipped_seen, skipped_no_bar,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
