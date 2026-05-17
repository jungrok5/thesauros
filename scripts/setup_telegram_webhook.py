"""One-shot script to register the Telegram webhook with our Vercel route.

Run AFTER your site is deployed and you know the public URL.

Usage:
    python -m scripts.setup_telegram_webhook https://your-domain.vercel.app
    python -m scripts.setup_telegram_webhook --delete    # unregister webhook

Reads TELEGRAM_BOT_TOKEN + TELEGRAM_WEBHOOK_SECRET from .env (or
web-next/.env.local — values should match in both).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")
# Fall back to web-next/.env.local for users who only set it there.
load_dotenv(_ROOT / "web-next" / ".env.local", override=False)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Register or delete a Telegram webhook.")
    p.add_argument("base_url", nargs="?", default=None,
                   help="Vercel domain root, e.g. https://thesauros.vercel.app")
    p.add_argument("--delete", action="store_true",
                   help="unregister the webhook (clears it on Telegram's side)")
    p.add_argument("--info", action="store_true",
                   help="just print current webhook info")
    args = p.parse_args(argv)

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    if not token:
        print("[FAIL] TELEGRAM_BOT_TOKEN missing in .env")
        return 1

    api = f"https://api.telegram.org/bot{token}"

    if args.info:
        r = requests.get(f"{api}/getWebhookInfo", timeout=15)
        print(r.text)
        return 0 if r.ok else 1

    if args.delete:
        r = requests.post(f"{api}/deleteWebhook", timeout=15)
        print(r.text)
        return 0 if r.ok else 1

    if not args.base_url:
        print("[FAIL] please pass your Vercel URL, e.g.")
        print("       python -m scripts.setup_telegram_webhook https://your-domain.vercel.app")
        return 1
    if not secret:
        print("[FAIL] TELEGRAM_WEBHOOK_SECRET missing in .env")
        return 1

    url = args.base_url.rstrip("/") + "/api/telegram/webhook"
    print(f"setting webhook → {url}")
    r = requests.post(
        f"{api}/setWebhook",
        json={
            "url": url,
            "secret_token": secret,
            "allowed_updates": ["message"],
        },
        timeout=15,
    )
    print(r.text)
    return 0 if r.ok and r.json().get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
