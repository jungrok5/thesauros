"""Paper-position alert worker (2026-05-27 reform).

Phase 2 of forward-test ported to the new broker-standard schema:
paper_positions + paper_fills. Fires Telegram + push when an OPEN
position's current weekly close has crossed its initial_stop_loss
or initial_target.

Dedup uses a sentinel row inside paper_fills (side='sell', shares=0,
reason='ALERT:stop'/'ALERT:target', amount=0). Once written, the
worker's WHERE clause excludes that position from the alert kind
on subsequent runs. We use a sentinel-fill instead of a column on
paper_positions because (a) the alert is logically a fill event,
(b) it stays queryable per kind without schema sprawl.

Usage:
    python -m app.db.notify_paper_alerts
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402
from app.db.webpush import is_available as webpush_available, send_many  # noqa: E402

log = logging.getLogger("notify_paper_alerts")

_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")


def _send_telegram(chat_id: str, text: str) -> bool:
    if not _BOT_TOKEN or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=10,
        )
        if resp.status_code >= 400:
            log.warning("telegram %s: %s", resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as e:
        log.warning("telegram send failed: %s", e)
        return False


def _fetch_open_unalerted(conn) -> List[Dict[str, Any]]:
    """Open positions where the current weekly close has crossed the
    initial stop/target AND we haven't fired that kind of alert
    before for this position."""
    sql = """
        SELECT  pp.id, pp.user_id, pp.ticker,
                pp.initial_entry_price, pp.initial_stop_loss, pp.initial_target,
                pp.total_invested_krw, pp.shares_open,
                latest.close AS current_price,
                u.email,
                u.telegram_chat_id,
                exists (
                  SELECT 1 FROM paper_fills f
                  WHERE  f.position_id = pp.id
                    AND  f.side = 'sell'
                    AND  f.reason = 'ALERT:stop'
                ) AS stop_alerted,
                exists (
                  SELECT 1 FROM paper_fills f
                  WHERE  f.position_id = pp.id
                    AND  f.side = 'sell'
                    AND  f.reason = 'ALERT:target'
                ) AS target_alerted
        FROM    paper_positions pp
                JOIN users u ON u.id::text = pp.user_id
                JOIN LATERAL (
                  SELECT close FROM bars
                  WHERE  ticker = pp.ticker AND granularity = 'W'
                  ORDER  BY bar_date DESC LIMIT 1
                ) latest ON true
        WHERE   pp.status = 'open'
          AND   pp.shares_open > 0
          AND (
            (pp.initial_stop_loss IS NOT NULL AND latest.close <= pp.initial_stop_loss)
            OR
            (pp.initial_target    IS NOT NULL AND latest.close >= pp.initial_target)
          )
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _format_message(kind: str, p: Dict[str, Any]) -> str:
    ticker = p["ticker"]
    entry  = float(p["initial_entry_price"]) if p["initial_entry_price"] else 0
    cur    = float(p["current_price"])
    pnl_pct = (cur / entry - 1) * 100 if entry > 0 else 0
    amt    = int(p["total_invested_krw"])
    # [모의투자] source tag — mirrors the [관심]/[보유] tag the watchlist
    # alerts use (2026-05-27 redesign). Tells users which list this
    # came from so it doesn't get confused with real-money signals.
    if kind == "stop":
        head = f"⚠️ <b>[모의투자] {ticker}</b> 주봉 10MA 손절선 도달"
        body = (
            f"진입 {entry:,.0f}원 → 현재 {cur:,.0f}원 ({pnl_pct:+.1f}%)\n"
            f"투자액 {amt//10_000:,}만원\n\n"
            f"👉 다음 단계:\n"
            f"   1) 책: 추세 사망 = 원칙적으로 즉시 청산\n"
            f"   2) 망설임 없이 손절. 다음 자리에서 다시 시작.\n\n"
            f"📅 매수/매도 결정은 금요일 15:30 종가 기준 · 일중 흔들림 무시.\n"
            f"<a href=\"https://thesauros2026.vercel.app/paper\">/paper 에서 청산</a>"
        )
    else:
        head = f"🎯 <b>[모의투자] {ticker}</b> 목표가 도달"
        body = (
            f"진입 {entry:,.0f}원 → 현재 {cur:,.0f}원 ({pnl_pct:+.1f}%)\n"
            f"투자액 {amt//10_000:,}만원\n\n"
            f"👉 다음 단계:\n"
            f"   1) 책: 일부 익절 검토 (50% 매도 권장)\n"
            f"   2) 추세 살아있으면 나머지 보유, 손절선 끌어올리기\n\n"
            f"📅 매수/매도 결정은 금요일 15:30 종가 기준 · 일중 흔들림 무시.\n"
            f"<a href=\"https://thesauros2026.vercel.app/paper\">/paper 에서 확인</a>"
        )
    return head + "\n" + body


def _send_push(conn, user_id: str, kind: str, p: Dict[str, Any]) -> int:
    if not webpush_available():
        return 0
    with conn.cursor() as cur:
        cur.execute(
            "SELECT endpoint, p256dh, auth FROM push_subscriptions "
            "WHERE user_id = %s", (user_id,))
        cols = [d[0] for d in cur.description]
        subs = [dict(zip(cols, r)) for r in cur.fetchall()]
    if not subs:
        return 0
    cur_price = float(p["current_price"])
    entry = float(p["initial_entry_price"]) if p["initial_entry_price"] else 0
    pnl_pct = (cur_price / entry - 1) * 100 if entry > 0 else 0
    title = (f"⚠ {p['ticker']} 손절선 도달"
             if kind == "stop"
             else f"🎯 {p['ticker']} 목표가 도달")
    body  = f"진입 대비 {pnl_pct:+.1f}%"
    payload = {
        "title": title, "body": body, "url": "/paper",
        "tag": f"paper-{p['id']}-{kind}",
    }
    result = send_many(subs, payload)
    if result.get("gone"):
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM push_subscriptions WHERE endpoint = ANY(%s)",
                (result["gone"],))
    return len(result.get("sent", []))


def _stamp_sentinel(conn, position_id: str, user_id: str, kind: str) -> None:
    """Write a zero-share, zero-amount sentinel fill so the WHERE
    clause above can exclude us on the next run. side='sell' to keep
    the CHECK constraint happy; the UI excludes ALERT:* fills from
    the fill log via reason filter (see /paper page)."""
    reason = f"ALERT:{kind}"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO paper_fills (
                position_id, user_id, side, fill_price, shares,
                amount_krw, reason, alert_sent_at
            )
            VALUES (%s, %s, 'sell', 0.0001, 0.0001, 0.0001, %s, now())
            """,
            (position_id, user_id, reason),
        )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    t0 = time.time()
    sent_stop = 0
    sent_target = 0
    with get_conn() as conn:
        rows = _fetch_open_unalerted(conn)
        log.info("open positions crossing stop/target: %d", len(rows))
        for p in rows:
            cur_price = float(p["current_price"])
            stop_cross = (p["initial_stop_loss"] is not None
                          and cur_price <= float(p["initial_stop_loss"])
                          and not p["stop_alerted"])
            target_cross = (p["initial_target"] is not None
                            and cur_price >= float(p["initial_target"])
                            and not p["target_alerted"])
            if stop_cross:
                kind = "stop"
            elif target_cross:
                kind = "target"
            else:
                continue
            msg = _format_message(kind, p)
            tg_ok = bool(p.get("telegram_chat_id")) and _send_telegram(
                p["telegram_chat_id"], msg,
            )
            push_n = _send_push(conn, p["user_id"], kind, p)
            _stamp_sentinel(conn, p["id"], p["user_id"], kind)
            if kind == "stop":
                sent_stop += 1
            else:
                sent_target += 1
            log.info("alert %s %s → telegram=%s push=%d",
                     kind, p["ticker"], tg_ok, push_n)
        conn.commit()
    log.info("done in %.1fs: stop=%d target=%d",
             time.time() - t0, sent_stop, sent_target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
