"""Telegram bot listener — handles the `/link <token>` flow.

Long-polls `getUpdates` (no webhook needed for free hosting). When a user
sends `/link <token>` to @candle_trend_bot, we POST it to
`{WEB_BASE}/api/telegram/consume` with the shared `TELEGRAM_LINK_SECRET`
header, which stamps `users.telegram_chat_id`.

Designed to run on Render Free (web-service or background worker) or on the
local Windows box. Single-process; resumes via offset persisted in
`telegram_bot_state.txt` next to this module.

Usage:
    python -m app.db.telegram_bot
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

log = logging.getLogger("telegram_bot")

STATE_FILE = Path(__file__).with_name("telegram_bot_state.txt")
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

HELP_TEXT = (
    "👋 Thesauros 캔들 추세 봇\n\n"
    "사용법:\n"
    "  /link <토큰>   — 웹사이트 /settings/alerts 에서 발급한 토큰 입력\n"
    "  /unlink        — 이 채팅의 알림 구독 해제\n"
    "  /help          — 도움말\n"
)


def _bot_token() -> str:
    t = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not t:
        raise RuntimeError("TELEGRAM_BOT_TOKEN missing")
    return t


def _web_base() -> str:
    return os.environ.get("WEB_BASE_URL", "http://localhost:3000").rstrip("/")


def _link_secret() -> str:
    s = os.environ.get("TELEGRAM_LINK_SECRET")
    if not s:
        raise RuntimeError("TELEGRAM_LINK_SECRET missing (also set on web-next)")
    return s


def _load_offset() -> int:
    try:
        return int(STATE_FILE.read_text().strip())
    except Exception:
        return 0


def _save_offset(n: int) -> None:
    try:
        STATE_FILE.write_text(str(n))
    except Exception as e:
        log.warning("offset save failed: %s", e)


def send_message(chat_id: int | str, text: str) -> None:
    try:
        requests.post(
            TELEGRAM_API.format(token=_bot_token(), method="sendMessage"),
            data={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": "true"},
            timeout=10,
        )
    except Exception as e:
        log.warning("send_message failed: %s", e)


def handle_link(chat_id: int, token: str) -> None:
    try:
        r = requests.post(
            f"{_web_base()}/api/telegram/consume",
            headers={
                "x-bot-secret": _link_secret(),
                "Content-Type": "application/json",
            },
            json={"token": token, "chat_id": str(chat_id)},
            timeout=10,
        )
    except Exception as e:
        send_message(chat_id, f"❌ 서버 연결 실패: {e}")
        return
    if r.ok:
        send_message(
            chat_id,
            "✅ 연동 완료!\n"
            "이제 관심 종목에 신호가 발생하면 이 채팅으로 알림이 옵니다.\n"
            "/settings/alerts 에서 알림 종류를 세분화할 수 있습니다.",
        )
    elif r.status_code == 404:
        send_message(chat_id, "❌ 알 수 없는 토큰입니다. 웹사이트에서 다시 발급해주세요.")
    elif r.status_code == 410:
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if body.get("error") == "expired":
            send_message(chat_id, "❌ 만료된 토큰입니다. 새로 발급해주세요.")
        else:
            send_message(chat_id, "❌ 이미 사용된 토큰입니다.")
    elif r.status_code == 403:
        send_message(chat_id, "❌ 봇 인증 실패 (관리자 문의).")
    else:
        send_message(chat_id, f"❌ 연동 실패 (HTTP {r.status_code}).")


def handle_message(msg: Dict[str, Any]) -> None:
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()
    if not chat_id or not text:
        return
    if text.startswith("/start") or text.startswith("/help"):
        send_message(chat_id, HELP_TEXT)
        return
    if text.startswith("/link"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2 or len(parts[1].strip()) < 8:
            send_message(chat_id, "사용법: <code>/link &lt;토큰&gt;</code>")
            return
        handle_link(int(chat_id), parts[1].strip())
        return
    if text.startswith("/unlink"):
        # Best-effort: just tell the user to use the web. We don't expose a
        # bot→web "force-unlink by chat_id" endpoint because that would let
        # anyone unsubscribe anyone else if they guess the chat_id.
        send_message(
            chat_id,
            "웹사이트 /settings/alerts 페이지에서 '해제' 버튼을 눌러주세요.",
        )
        return
    send_message(chat_id, HELP_TEXT)


def poll_forever() -> None:
    offset = _load_offset()
    log.info("starting long-poll loop (offset=%d)", offset)
    while True:
        try:
            r = requests.get(
                TELEGRAM_API.format(token=_bot_token(), method="getUpdates"),
                params={"offset": offset, "timeout": 25, "allowed_updates": '["message"]'},
                timeout=30,
            )
        except Exception as e:
            log.warning("getUpdates failed: %s", e)
            time.sleep(5)
            continue
        if not r.ok:
            log.warning("getUpdates HTTP %s: %s", r.status_code, r.text[:200])
            time.sleep(5)
            continue
        updates = r.json().get("result", [])
        for u in updates:
            offset = max(offset, int(u["update_id"]) + 1)
            msg = u.get("message")
            if msg:
                try:
                    handle_message(msg)
                except Exception as e:
                    log.exception("handle_message error: %s", e)
        if updates:
            _save_offset(offset)


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true",
                   help="drain one batch and exit (for cron testing)")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if args.once:
        offset = _load_offset()
        r = requests.get(
            TELEGRAM_API.format(token=_bot_token(), method="getUpdates"),
            params={"offset": offset, "timeout": 0, "allowed_updates": '["message"]'},
            timeout=15,
        )
        for u in r.json().get("result", []):
            offset = max(offset, int(u["update_id"]) + 1)
            msg = u.get("message")
            if msg:
                handle_message(msg)
        _save_offset(offset)
        return 0
    poll_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
