"""Print the env keys + values that need to be registered as
GitHub Actions repository secrets.

This makes the manual copy-paste step into the GitHub UI a lot less
error-prone. Run locally, then paste each Name/Value pair into
https://github.com/<you>/<repo>/settings/secrets/actions

The script reads from .env (Python cron variables) so you must run
it on the box where .env is filled.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")

# Keys the GitHub Actions workflows actually reference.
REQUIRED = [
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "SUPABASE_DB_PASSWORD",
    "FRED_API_KEY",
    "DART_API_KEY",
    "KIS_APP_KEY",
    "KIS_APP_SECRET",
    "KIS_ACCOUNT_NO",
    "KIS_ACCOUNT_PROD_CODE",
    "SEC_USER_AGENT",
    "TELEGRAM_BOT_TOKEN",
    "VAPID_PUBLIC_KEY",       # only if PWA push enabled
    "VAPID_PRIVATE_KEY",
    "VAPID_CONTACT_EMAIL",
]

print("Register these on https://github.com/<user>/<repo>/settings/secrets/actions")
print("=" * 70)
for k in REQUIRED:
    v = os.environ.get(k, "")
    if v:
        # Show first 8 chars only for readability
        preview = v if len(v) <= 16 else v[:8] + "...(len " + str(len(v)) + ")"
        print(f"  {k:<28} = {preview}")
    else:
        print(f"  {k:<28} = !!! MISSING in .env !!!")
print()
print("Tip: open .env to copy the full value into GitHub's secret-value box.")
