"""Paper-trade alert worker — fires Telegram + web-push when an
open paper_trade hits its stop_loss or target.

Phase 2 of forward-test: paired with the buy/track/close loop the
user now drives manually, this lets the system speak first. Cron
runs once a day (after ingest_bars updates the in-progress weekly
close), checks every open paper_trade, and:

  · current_price <= stop_loss  AND stop_alert_sent_at IS NULL
      → alert: "10MA 손절선 도달 — 청산 권장"
      → stamp stop_alert_sent_at = now()
  · current_price >= target     AND target_alert_sent_at IS NULL
      → alert: "목표가 도달 — 일부 익절 검토"
      → stamp target_alert_sent_at = now()

Stamps are one-shot per trade — once sent, the row stops
participating in this worker even if the price oscillates. Cron is
idempotent w.r.t. duplicate runs.

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
    """Open paper_trades where at least one of stop / target alerts is
    still un-fired AND the live ticker price triggered the cross."""
    sql = """
        SELECT  pt.id, pt.user_id, pt.ticker, pt.entry_price,
                pt.stop_loss, pt.target, pt.amount_krw,
                pt.stop_alert_sent_at, pt.target_alert_sent_at,
                latest.close AS current_price,
                u.email,
                u.telegram_chat_id
        FROM    paper_trades pt
                JOIN users u ON u.id::text = pt.user_id
                JOIN LATERAL (
                  SELECT close FROM bars
                  WHERE  ticker = pt.ticker AND granularity = 'W'
                  ORDER  BY bar_date DESC LIMIT 1
                ) latest ON true
        WHERE   pt.status = 'open'
          AND (
            (pt.stop_loss   IS NOT NULL
             AND latest.close <= pt.stop_loss
             AND pt.stop_alert_sent_at IS NULL)
            OR
            (pt.target      IS NOT NULL
             AND latest.close >= pt.target
             AND pt.target_alert_sent_at IS NULL)
          )
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _format_message(kind: str, trade: Dict[str, Any]) -> str:
    """Compose the user-facing alert body. Kind = 'stop' | 'target'.
    HTML-safe (Telegram parse_mode=HTML)."""
    ticker = trade["ticker"]
    entry  = float(trade["entry_price"])
    cur    = float(trade["current_price"])
    pnl_pct = (cur / entry - 1) * 100
    amt    = int(trade["amount_krw"])
    if kind == "stop":
        head = f"⚠️ <b>{ticker}</b> 주봉 10MA 손절선 도달"
        body = (
            f"진입 {entry:,.0f}원 → 현재 {cur:,.0f}원 ({pnl_pct:+.1f}%)\n"
            f"투자액 {amt//10_000:,}만원 · 책: 추세 사망 = 즉시 청산.\n"
            f"<a href=\"https://thesauros2026.vercel.app/paper\">/paper 에서 청산</a>"
        )
    else:
        head = f"🎯 <b>{ticker}</b> 목표가 도달"
        body = (
            f"진입 {entry:,.0f}원 → 현재 {cur:,.0f}원 ({pnl_pct:+.1f}%)\n"
            f"투자액 {amt//10_000:,}만원 · 책: 일부 익절 검토, 추세 살아있으면 보유.\n"
            f"<a href=\"https://thesauros2026.vercel.app/paper\">/paper 에서 확인</a>"
        )
    return head + "\n" + body


def _send_push(conn, user_id: str, kind: str, trade: Dict[str, Any]) -> int:
    """Web push fan-out to all subscriptions for this user. Cleans up
    expired endpoints (404/410) the same way telegram_worker does."""
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
    title = (f"⚠ {trade['ticker']} 손절선 도달"
             if kind == "stop"
             else f"🎯 {trade['ticker']} 목표가 도달")
    body  = (f"진입 대비 "
             f"{((float(trade['current_price'])/float(trade['entry_price']) - 1) * 100):+.1f}%")
    payload = {
        "title": title,
        "body": body,
        "url": "/paper",
        "tag": f"paper-{trade['id']}-{kind}",
    }
    result = send_many(subs, payload)
    if result.get("gone"):
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM push_subscriptions WHERE endpoint = ANY(%s)",
                (result["gone"],))
    return len(result.get("sent", []))


def _stamp(conn, trade_id: str, kind: str) -> None:
    col = "stop_alert_sent_at" if kind == "stop" else "target_alert_sent_at"
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE paper_trades SET {col} = now() WHERE id = %s",
            (trade_id,),
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
        log.info("open paper_trades needing alert: %d", len(rows))
        for trade in rows:
            cur = float(trade["current_price"])
            stop_hit = (trade["stop_loss"] is not None
                        and cur <= float(trade["stop_loss"])
                        and trade["stop_alert_sent_at"] is None)
            target_hit = (trade["target"] is not None
                          and cur >= float(trade["target"])
                          and trade["target_alert_sent_at"] is None)
            # Book priority: stop wins over target in the same bar — if
            # somehow both crossed simultaneously, the loss signal is the
            # one the user needs to act on first.
            if stop_hit:
                kind = "stop"
            elif target_hit:
                kind = "target"
            else:
                continue
            msg = _format_message(kind, trade)
            tg_ok = bool(trade.get("telegram_chat_id")) and _send_telegram(
                trade["telegram_chat_id"], msg,
            )
            push_n = _send_push(conn, trade["user_id"], kind, trade)
            _stamp(conn, trade["id"], kind)
            if kind == "stop":
                sent_stop += 1
            else:
                sent_target += 1
            log.info("alert %s %s → telegram=%s push=%d",
                     kind, trade["ticker"], tg_ok, push_n)
        conn.commit()
    log.info("done in %.1fs: stop=%d target=%d",
             time.time() - t0, sent_stop, sent_target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
