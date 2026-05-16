"""Telegram alert worker — sends signal changes to subscribed users.

How it works (idempotent, safe to re-run):
  1. For every user with a telegram_chat_id, look at their watchlist.
  2. For each watched ticker, find active scan_results signals.
  3. Compare against `alerts` table — emit a row only if the same
     (user_id, ticker, alert_type) row isn't already present *for this
     detected_at timestamp*.
  4. Send the new alert messages to Telegram, mark sent_telegram=true.

Designed to be called from GitHub Actions cron after `scan_daily.py`,
so signals are already fresh in `scan_results`.

Alert types mapped from scan_results.signal_type:
  - action_strong_buy / action_buy → 'enter' (severity info)
  - action_sell / action_sell_short → 'exit'  (severity critical)
  - pattern_* (bullish)             → 'pyramid' if already holding
  - volume_case_9 / death_messenger → 'warn'
  - ma240_break_down                → 'exit'

Usage:
    python -m app.db.telegram_worker
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402

log = logging.getLogger("telegram_worker")


# ---- Mapping: scan_results.signal_type → alert.alert_type, severity ----

ALERT_RULES: List[Tuple[str, str, str]] = [
    # (signal_type_prefix_or_exact, alert_type, severity)
    ("action_strong_buy",       "enter",    "info"),
    ("action_buy",              "enter",    "info"),
    ("action_sell_short",       "exit",     "critical"),
    ("action_sell",             "exit",     "critical"),
    ("volume_case_9",           "warn",     "warn"),
    ("volume_case_10",          "warn",     "warn"),
    ("pattern_death_messenger", "exit",     "critical"),
    ("ma240_break_down",        "exit",     "critical"),
    ("pattern_double_top",      "warn",     "warn"),
    ("pattern_head_and_shoulders", "warn",  "warn"),
    ("pattern_triple_top",      "warn",     "warn"),
    # bullish patterns → pyramid signal (only fires for holding category)
    ("pattern_double_bottom",   "pyramid",  "info"),
    ("pattern_inverse_head_and_shoulders", "pyramid", "info"),
    ("pattern_triple_bottom",   "pyramid",  "info"),
    ("pattern_cup_and_handle",  "pyramid",  "info"),
    ("pattern_doulbanji",       "pyramid",  "info"),
]


def classify(signal_type: str) -> Optional[Tuple[str, str]]:
    """signal_type → (alert_type, severity) or None to skip."""
    for prefix, atype, sev in ALERT_RULES:
        if signal_type == prefix or signal_type.startswith(prefix + "_"):
            return atype, sev
    return None


# ---- Telegram send ------------------------------------------------------

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram(chat_id: str, text: str, *, token: Optional[str] = None) -> bool:
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        log.error("TELEGRAM_BOT_TOKEN missing")
        return False
    url = TELEGRAM_API.format(token=token)
    try:
        r = requests.post(url, data={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }, timeout=10)
        if not r.ok:
            log.warning("telegram send failed (%s): %s", r.status_code, r.text[:200])
            return False
        return True
    except Exception as e:
        log.warning("telegram send error: %s", e)
        return False


# ---- DB queries --------------------------------------------------------

def _users_with_telegram() -> List[Dict[str, Any]]:
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, telegram_chat_id FROM users "
                "WHERE telegram_chat_id IS NOT NULL"
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def _watchlist_active(user_id: str) -> List[Dict[str, Any]]:
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ticker, category FROM watchlist "
                "WHERE user_id = %s AND alerts_enabled = true",
                (user_id,),
            )
            return [{"ticker": r[0], "category": r[1]} for r in cur.fetchall()]


def _active_signals_for(tickers: List[str]) -> List[Dict[str, Any]]:
    if not tickers:
        return []
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, ticker, signal_type, timeframe, detected_at, strength, reason "
                "FROM scan_results WHERE is_active = true AND ticker = ANY(%s)",
                (tickers,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def _already_alerted(user_id: str, ticker: str, alert_type: str,
                     signal_detected_at: str) -> bool:
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM alerts WHERE user_id = %s AND ticker = %s "
                "AND alert_type = %s AND created_at >= %s LIMIT 1",
                (user_id, ticker, alert_type, signal_detected_at),
            )
            return cur.fetchone() is not None


def _insert_alert(user_id: str, ticker: str, alert_type: str, message: str,
                  severity: str, sent: bool) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alerts (user_id, ticker, alert_type, message,
                                    severity, sent_telegram, sent_at)
                VALUES (%s, %s, %s, %s, %s, %s, CASE WHEN %s THEN now() ELSE NULL END)
                """,
                (user_id, ticker, alert_type, message, severity, sent, sent),
            )


def _ticker_name(ticker: str) -> Optional[str]:
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM tickers WHERE ticker = %s", (ticker,))
            r = cur.fetchone()
            return r[0] if r else None


# ---- Driver ------------------------------------------------------------

def format_message(ticker: str, name: Optional[str], alert_type: str,
                   sig: Dict[str, Any]) -> str:
    badge = {
        "enter":    "🟢 [매수 신호]",
        "pyramid":  "🟡 [추가매수 신호]",
        "warn":     "🟠 [경고]",
        "exit":     "🔴 [청산 권장]",
    }.get(alert_type, "📊")
    title = f"{badge} {ticker} {name or ''}"
    body = sig.get("reason") or sig.get("signal_type", "")
    strength = sig.get("strength")
    tf = sig.get("timeframe")
    lines = [
        f"<b>{title}</b>",
        f"📊 {body}",
        f"⏱ {tf} · 강도 {float(strength):.2f}" if strength is not None else f"⏱ {tf}",
    ]
    return "\n".join(lines)


def run_once(dry_run: bool = False) -> Dict[str, int]:
    stats = {"users": 0, "watched_tickers": 0, "new_alerts": 0, "sent": 0,
             "skipped_existing": 0}

    users = _users_with_telegram()
    stats["users"] = len(users)
    if not users:
        log.info("no users with telegram_chat_id")
        return stats

    for u in users:
        watch = _watchlist_active(u["id"])
        if not watch:
            continue
        tickers = [w["ticker"] for w in watch]
        category_by_ticker = {w["ticker"]: w["category"] for w in watch}
        stats["watched_tickers"] += len(tickers)
        signals = _active_signals_for(tickers)
        if not signals:
            continue
        # group by (ticker, alert_type) — keep highest strength
        best: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for s in signals:
            cls = classify(s["signal_type"])
            if not cls:
                continue
            atype, sev = cls
            # For PYRAMID (bullish pattern), only fire if user is holding
            if atype == "pyramid" and category_by_ticker.get(s["ticker"]) != "holding":
                continue
            k = (s["ticker"], atype)
            if k not in best or float(s["strength"] or 0) > float(best[k]["strength"] or 0):
                best[k] = {**s, "alert_type": atype, "severity": sev}

        for (ticker, atype), sig in best.items():
            sig_at = sig["detected_at"]
            if _already_alerted(u["id"], ticker, atype, sig_at):
                stats["skipped_existing"] += 1
                continue
            name = _ticker_name(ticker)
            msg = format_message(ticker, name, atype, sig)
            sent = False
            if not dry_run:
                sent = send_telegram(u["telegram_chat_id"], msg)
                _insert_alert(u["id"], ticker, atype, msg, sig["severity"], sent)
            stats["new_alerts"] += 1
            if sent:
                stats["sent"] += 1
                time.sleep(0.3)   # avoid telegram rate limit (~30 msg/sec, well under)
    return stats


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="don't send telegram messages or insert rows")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    stats = run_once(dry_run=args.dry_run)
    log.info("done: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
