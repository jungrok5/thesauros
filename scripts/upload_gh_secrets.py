"""Upload all required GitHub Actions secrets in one shot.

Reads from .env and calls `gh secret set NAME --body VALUE` for each key
the workflows reference. Safer than copy-pasting 14 values into the
GitHub UI by hand.

Usage:
    python -m scripts.upload_gh_secrets             # uploads all
    python -m scripts.upload_gh_secrets --dry-run   # preview only

Requires: gh CLI authenticated to the repo (`gh auth status`).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")

# Keys the workflows in .github/workflows/*.yml actually use.
KEYS = [
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
    "VAPID_PUBLIC_KEY",
    "VAPID_PRIVATE_KEY",
    "VAPID_CONTACT_EMAIL",
]


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="show what would be uploaded, but don't run gh")
    args = p.parse_args(argv)

    # Pre-check gh is on PATH and authed (capture as bytes to dodge cp949)
    try:
        r = subprocess.run(["gh", "auth", "status"], capture_output=True)
        if r.returncode != 0:
            print("[FAIL] gh CLI not authenticated. Run: gh auth login")
            return 1
    except FileNotFoundError:
        print("[FAIL] gh CLI not installed. https://cli.github.com/")
        return 1

    missing = [k for k in KEYS if not os.environ.get(k)]
    if missing:
        print("[FAIL] missing in .env:", ", ".join(missing))
        return 1

    print(f"about to upload {len(KEYS)} secrets" +
          (" (DRY RUN)" if args.dry_run else "") + "...\n")

    failures = []
    for k in KEYS:
        v = os.environ[k]
        preview = v[:8] + "..." if len(v) > 12 else v
        print(f"  {k:<28} = {preview}")
        if args.dry_run:
            continue
        r = subprocess.run(
            ["gh", "secret", "set", k, "--body", v],
            capture_output=True,
        )
        if r.returncode != 0:
            err = r.stderr.decode("utf-8", errors="replace").strip()
            print(f"    [FAIL] {err}")
            failures.append(k)

    print()
    if args.dry_run:
        print("dry run complete. pass without --dry-run to apply.")
    elif failures:
        print(f"[PARTIAL] {len(failures)} failed: {', '.join(failures)}")
        return 1
    else:
        print(f"[OK] {len(KEYS)} secrets uploaded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
