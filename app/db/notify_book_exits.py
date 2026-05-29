"""Book-faithful exit Telegram alerts — replaces notify_stop_loss.py.

Pipeline (runs as a weekly cron step, after Friday weekly bar close):

  1. Build (user, ticker, entry_price, entry_at) for every alert-enabled
     holding with a chat_id.
  2. For each holding, evaluate two book exits:
       a) 종목별 월봉 10MA 깨짐 — latest monthly close < 10-month MA.
       b) 장대양봉 4등분 25% 깨짐 — if the entry-week bar qualifies as
          a 장대양봉 per app.book.exits, check whether the LATEST weekly
          close has fallen below `open + 0.25 × (close − open)`.
  3. Dedup against `book_exit_alert_seen` on
     (user_id, ticker, kind, bar_date) — never alert twice for the same
     week + rule + user.
  4. Insert into `alerts` + send Telegram. Idempotent.

The 천장 패턴 exit class (쌍봉 / 머리어깨 / 삼중천장 / action_sell) is
already covered by telegram_worker's existing exit alerts — no
duplication here.

The legacy -10% % stop alert (notify_stop_loss.py) was retired
2026-05-29: book never prescribes a fixed % stop, and the walk-forward
audit confirmed book-rule exits both back-tested better and matched
사용자 expectations of "책 그대로 사고팔자".

usage:
    python -m app.db.notify_book_exits
    python -m app.db.notify_book_exits --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn                            # noqa: E402
from app.db.telegram_worker import send_telegram       # noqa: E402
from app.book.exits import (                           # noqa: E402
    is_jangdae_yangbong,
    quartile_25_level,
    monthly_10ma_broken,
    LONG_BULLISH_AVG_WINDOW,
    MONTHLY_MA_WINDOW,
)

log = logging.getLogger("notify_book_exits")


# ─────────────────────────────────────────────────────────────────────
# Holdings + bar fetchers
# ─────────────────────────────────────────────────────────────────────
def _holdings() -> List[Tuple[str, str, str, float, Optional[date], str]]:
    """Returns [(user_id, ticker, name, entry_price, entry_at, chat_id)]
    for every alert-enabled holding with a chat_id set."""
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.id::text, w.ticker, t.name, w.entry_price,
                       w.entry_date::date, u.telegram_chat_id
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
                (r[0], r[1], r[2] or r[1], float(r[3]), r[4], r[5])
                for r in cur.fetchall()
            ]


def _bulk_weekly_bars(
    tickers: List[str], min_bars: int,
) -> Dict[str, List[Tuple[date, float, float, float, float]]]:
    """{ticker: [(bar_date, open, high, low, close)]} sorted ASC.
    Pulls up to `min_bars+5` recent weekly bars per ticker for the
    장대양봉 rolling-avg context. Single round-trip via window function.
    """
    if not tickers:
        return {}
    out: Dict[str, List[Tuple[date, float, float, float, float]]] = {
        t: [] for t in tickers
    }
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH ranked AS (
                  SELECT ticker, bar_date, open, high, low, close,
                         ROW_NUMBER() OVER (
                             PARTITION BY ticker ORDER BY bar_date DESC
                         ) AS rn
                    FROM bars
                   WHERE ticker = ANY(%s) AND granularity = 'W'
                )
                SELECT ticker, bar_date, open, high, low, close
                  FROM ranked WHERE rn <= %s
                  ORDER BY ticker, bar_date
                """,
                (tickers, int(min_bars) + 5),
            )
            for ticker, bd, o, h, l, c in cur.fetchall():
                if any(v is None for v in (o, h, l, c)):
                    continue
                out[ticker].append((bd, float(o), float(h), float(l), float(c)))
    return out


def _bulk_monthly_closes(
    tickers: List[str], min_bars: int,
) -> Dict[str, List[Tuple[date, float]]]:
    """{ticker: [(bar_date, close)]} sorted ASC. min_bars+2 most recent."""
    if not tickers:
        return {}
    out: Dict[str, List[Tuple[date, float]]] = {t: [] for t in tickers}
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH ranked AS (
                  SELECT ticker, bar_date, close,
                         ROW_NUMBER() OVER (
                             PARTITION BY ticker ORDER BY bar_date DESC
                         ) AS rn
                    FROM bars
                   WHERE ticker = ANY(%s) AND granularity = 'M'
                )
                SELECT ticker, bar_date, close
                  FROM ranked WHERE rn <= %s
                  ORDER BY ticker, bar_date
                """,
                (tickers, int(min_bars) + 2),
            )
            for ticker, bd, c in cur.fetchall():
                if c is None:
                    continue
                out[ticker].append((bd, float(c)))
    return out


# ─────────────────────────────────────────────────────────────────────
# Dedup
# ─────────────────────────────────────────────────────────────────────
def _bulk_seen(
    pairs: List[Tuple[str, str, str, str]],
) -> set:
    """Subset of input (user, ticker, kind, bar_date) already in
    book_exit_alert_seen."""
    if not pairs:
        return set()
    out = set()
    user_ids = [p[0] for p in pairs]
    tickers = [p[1] for p in pairs]
    kinds = [p[2] for p in pairs]
    dates = [p[3] for p in pairs]
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id::text, ticker, kind, alerted_at_bar_date::text
                  FROM book_exit_alert_seen
                 WHERE user_id::text = ANY(%s)
                   AND ticker = ANY(%s)
                   AND kind = ANY(%s)
                   AND alerted_at_bar_date::text = ANY(%s)
                """,
                (user_ids, tickers, kinds, dates),
            )
            for u, t, k, d in cur.fetchall():
                out.add((str(u), str(t), str(k), str(d)))
    return out


def _mark_seen(
    user_id: str, ticker: str, kind: str, bar_date: date,
    entry_price: float, close: float, sent: bool,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO book_exit_alert_seen
                    (user_id, ticker, kind, alerted_at_bar_date,
                     entry_price, bar_close_price, sent_telegram)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, ticker, kind, alerted_at_bar_date)
                DO UPDATE SET sent_telegram = EXCLUDED.sent_telegram
                """,
                (user_id, ticker, kind, bar_date,
                 entry_price, close, sent),
            )


def _insert_alert(user_id: str, ticker: str, message: str, sent: bool,
                  alert_type: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alerts (user_id, ticker, alert_type, message,
                                    severity, sent_telegram, sent_at)
                VALUES (%s, %s, %s, %s, 'warn', %s,
                        CASE WHEN %s THEN now() ELSE NULL END)
                """,
                (user_id, ticker, alert_type, message, sent, sent),
            )


# ─────────────────────────────────────────────────────────────────────
# Message rendering — aligned with 2026-05-27 telegram redesign:
#   [출처] tag in title, 다음 단계 guide, 금요일 종가 reminder.
# ─────────────────────────────────────────────────────────────────────
def format_10ma_message(name: str, ticker: str, entry_price: float,
                        close: float, ma_value: float) -> str:
    delta_pct = (close - entry_price) / entry_price * 100.0
    return (
        f"⚠️ <b>[보유] {name}</b> ({ticker}) — 월봉 10MA 깨짐\n\n"
        f"등록가: <code>{entry_price:,.0f}</code>\n"
        f"이번 월 종가: <code>{close:,.0f}</code>\n"
        f"월봉 10MA: <code>{ma_value:,.0f}</code>\n"
        f"<b>등록가 대비: {delta_pct:+.2f}%</b>\n\n"
        f"📖 책의 \"가장 객관적인 추세선\" — 월봉 종가가 10MA 아래로 마감.\n"
        f"👉 다음 단계: 청산 권장. 추세가 끝난 신호.\n\n"
        f"📅 매수/매도 결정은 월/주 종가 기준 · 일중 흔들림 무시.\n"
        f"🔗 <a href=\"https://thesauros2026.vercel.app/stocks/{ticker}\">"
        f"상세 분석 ↗</a>"
    )


def format_quartile_message(name: str, ticker: str, entry_price: float,
                            close: float, q25: float) -> str:
    delta_pct = (close - entry_price) / entry_price * 100.0
    return (
        f"⚠️ <b>[보유] {name}</b> ({ticker}) — 장대양봉 4등분 25% 깨짐\n\n"
        f"등록가: <code>{entry_price:,.0f}</code>\n"
        f"이번 주 종가: <code>{close:,.0f}</code>\n"
        f"4등분 25%선: <code>{q25:,.0f}</code>\n"
        f"<b>등록가 대비: {delta_pct:+.2f}%</b>\n\n"
        f"📖 책 p218-223 — 매수 자리였던 장대양봉의 25% 아래로 종가 마감.\n"
        f"👉 다음 단계: 청산 권장. \"절대 자리 깨짐\".\n\n"
        f"📅 매수/매도 결정은 주봉 종가 기준 · 일중 흔들림 무시.\n"
        f"🔗 <a href=\"https://thesauros2026.vercel.app/stocks/{ticker}\">"
        f"상세 분석 ↗</a>"
    )


# ─────────────────────────────────────────────────────────────────────
# Driver
# ─────────────────────────────────────────────────────────────────────
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true",
                   help="Don't send Telegram or insert rows.")
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

    distinct = sorted({h[1] for h in holdings})
    weekly = _bulk_weekly_bars(distinct, LONG_BULLISH_AVG_WINDOW + 1)
    monthly = _bulk_monthly_closes(distinct, MONTHLY_MA_WINDOW)

    pending: List[Tuple] = []
    skipped_no_data = 0

    for user_id, ticker, name, entry_price, entry_date, chat_id in holdings:
        w_bars = weekly.get(ticker, [])
        m_bars = monthly.get(ticker, [])
        if not w_bars or not m_bars:
            skipped_no_data += 1
            continue
        latest_w = w_bars[-1]            # (bar_date, open, high, low, close)
        latest_m = m_bars[-1]

        # ─── (a) 종목별 월봉 10MA 깨짐 ────────────────────────────
        monthly_closes = [c for _, c in m_bars]
        broken = monthly_10ma_broken(monthly_closes)
        if broken:
            ma_val = sum(monthly_closes[-MONTHLY_MA_WINDOW:]) / MONTHLY_MA_WINDOW
            pending.append((
                user_id, ticker, name, entry_price, chat_id,
                "monthly_10ma", latest_m[0], float(latest_m[1]),
                ma_val,
            ))

        # ─── (b) 장대양봉 4등분 25% 깨짐 ──────────────────────────
        # Anchor: the weekly bar that contains entry_at.
        anchor = None
        if entry_date is not None:
            # Find weekly bar whose Friday is within 6 days after entry.
            for bd, o, h, l, c in w_bars:
                delta_days = (bd - entry_date).days
                if 0 <= delta_days <= 6:
                    anchor = (bd, o, h, l, c)
                    break
        if anchor is None:
            # Fallback: pick the most-recent week whose open ≤ entry_price ≤ close
            # (entry happened during that bar).
            for bd, o, h, l, c in w_bars:
                if min(o, c) <= entry_price <= max(o, c):
                    anchor = (bd, o, h, l, c)
                    break
        if anchor is not None:
            anchor_idx = next(
                (i for i, b in enumerate(w_bars) if b[0] == anchor[0]),
                None,
            )
            if anchor_idx is not None and anchor_idx >= 1:
                lo = max(0, anchor_idx - LONG_BULLISH_AVG_WINDOW)
                prior_bodies = [
                    abs(w_bars[i][4] - w_bars[i][1])
                    for i in range(lo, anchor_idx)
                ]
                if prior_bodies:
                    avg_body = sum(prior_bodies) / len(prior_bodies)
                    if is_jangdae_yangbong(anchor[1], anchor[4], avg_body):
                        q25 = quartile_25_level(anchor[1], anchor[4])
                        if latest_w[4] < q25:
                            pending.append((
                                user_id, ticker, name, entry_price, chat_id,
                                "quartile_25", latest_w[0],
                                float(latest_w[4]), q25,
                            ))

    # Dedup
    keys = [(p[0], p[1], p[5], str(p[6])) for p in pending]
    seen = _bulk_seen(keys)

    dispatched = 0
    skipped_seen = 0
    for (user_id, ticker, name, entry_price, chat_id, kind, bar_date,
         close, threshold_val) in pending:
        if (user_id, ticker, kind, str(bar_date)) in seen:
            skipped_seen += 1
            continue
        if kind == "monthly_10ma":
            message = format_10ma_message(
                name, ticker, entry_price, close, threshold_val,
            )
            alert_type = "monthly_10ma_break"
        else:
            message = format_quartile_message(
                name, ticker, entry_price, close, threshold_val,
            )
            alert_type = "quartile_25_break"
        sent = False
        if not args.dry_run and chat_id and token:
            try:
                sent = send_telegram(chat_id, message, token=token)
            except Exception as e:
                log.warning("telegram send failed user=%s ticker=%s kind=%s: %s",
                            user_id, ticker, kind, e)
                sent = False
        if not args.dry_run:
            _insert_alert(user_id, ticker, message, sent, alert_type)
            _mark_seen(user_id, ticker, kind, bar_date,
                       entry_price, close, sent)
        dispatched += 1
        log.info("[%s] user=%s ticker=%s close=%.0f sent=%s",
                 kind, user_id[:8], ticker, close, sent)

    log.info(
        "summary: holdings=%d dispatched=%d skipped_seen=%d skipped_no_data=%d",
        len(holdings), dispatched, skipped_seen, skipped_no_data,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
