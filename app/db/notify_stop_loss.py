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


def _bulk_latest_weekly_close(tickers: List[str]) -> Dict[str, Tuple[float, str]]:
    """2026-05-28 — bulk variant. Returns {ticker: (close, bar_date)}.

    Single round-trip vs N (one per holding) — meaningful for N>5 watchlist
    holdings. Uses DISTINCT ON to pick the latest bar per ticker.
    """
    if not tickers:
        return {}
    out: Dict[str, Tuple[float, str]] = {}
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (ticker) ticker, close, bar_date
                  FROM bars
                 WHERE ticker = ANY(%s) AND granularity = 'W'
              ORDER BY ticker, bar_date DESC
                """,
                (tickers,),
            )
            for ticker, close, bar_date in cur.fetchall():
                if close is None:
                    continue
                out[ticker] = (float(close), str(bar_date))
    return out


def _bulk_already_seen(
    pairs: List[Tuple[str, str, str]],
) -> set[Tuple[str, str, str]]:
    """2026-05-28 — bulk dedup lookup. Input list of (user_id, ticker, bar_date).
    Returns the subset already in stop_loss_alert_seen."""
    if not pairs:
        return set()
    seen: set[Tuple[str, str, str]] = set()
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            # Build the IN list as ROW values for a clean single query.
            user_ids = [p[0] for p in pairs]
            tickers = [p[1] for p in pairs]
            dates = [p[2] for p in pairs]
            cur.execute(
                """
                SELECT user_id, ticker, alerted_at_bar_date
                  FROM stop_loss_alert_seen
                 WHERE user_id::text = ANY(%s)
                   AND ticker = ANY(%s)
                   AND alerted_at_bar_date::text = ANY(%s)
                """,
                (user_ids, tickers, dates),
            )
            for u, t, d in cur.fetchall():
                seen.add((str(u), str(t), str(d)))
    return seen


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
    """Telegram HTML — [보유] 손절선 도달 메시지.

    Tone aligned with the 2026-05-27 telegram redesign: [출처] tag in
    title, 다음 단계 guide, 금요일 종가 기준 reminder. Matches the
    [관심] / [모의투자] pattern from telegram_worker.format_message.

    The SL threshold is a notification trigger, NOT a sell command —
    book spirit says weekly-close based decisions, not intraday panic.
    The guide tells the user how to respond per book principles.
    """
    return (
        f"⚠️ <b>[보유] {name}</b> ({ticker}) — 손절선 도달\n\n"
        f"등록가: <code>{entry_price:,.0f}</code>\n"
        f"이번 주봉 종가: <code>{close:,.0f}</code>\n"
        f"<b>변동: {drop_pct:+.2f}%</b> (임계 -{threshold:.0f}%)\n\n"
        f"👉 다음 단계:\n"
        f"   1) 차트 확인 — 추세 (월/주) 가 여전히 살아있나\n"
        f"   2) 진입 신호 강도/종류 점검 (강한 매수 신호였으면 청산 우선)\n"
        f"   3) 책 정신상 손절선 도달 = 청산 권장. 망설임 X.\n\n"
        f"📅 매수/매도 결정은 금요일 15:30 종가 기준 · 일중 흔들림 무시.\n"
        f"🔗 <a href=\"https://thesauros2026.vercel.app/stocks/{ticker}\">"
        f"상세 분석 ↗</a>"
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

    # 2026-05-28 — bulk-fetch latest weekly close + dedup state in two
    # round-trips instead of 2N. With N watchlist holdings this cut
    # ~50-100ms × N off the cron path.
    distinct_tickers = sorted({h[1] for h in holdings})
    bars_by_ticker = _bulk_latest_weekly_close(distinct_tickers)
    # First pass: figure out which (user, ticker, bar_date) tuples
    # actually need a dedup check — i.e. those whose drop is below
    # threshold. Avoids querying stop_loss_alert_seen for holdings
    # that aren't going to fire anyway.
    pending: List[Tuple[str, str, str, float, str, str, float, float]] = []
    for user_id, ticker, name, entry_price, chat_id in holdings:
        bar = bars_by_ticker.get(ticker)
        if not bar:
            skipped_no_bar += 1
            continue
        close, bar_date = bar
        drop_pct = (close - entry_price) / entry_price * 100.0
        if drop_pct > -args.threshold:
            above_threshold += 1
            continue
        pending.append((user_id, ticker, name, entry_price, chat_id,
                        bar_date, close, drop_pct))
    already_seen = _bulk_already_seen(
        [(p[0], p[1], p[5]) for p in pending],
    )
    for user_id, ticker, name, entry_price, chat_id, bar_date, close, drop_pct in pending:
        if (user_id, ticker, bar_date) in already_seen:
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
