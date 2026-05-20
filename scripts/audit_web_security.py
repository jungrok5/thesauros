"""One-shot security audit for web-next/src. Read-only static analysis.

Checks:
  1. dangerouslySetInnerHTML (XSS surface)
  2. API routes missing auth() check
  3. Open redirects (Location header from user input)
  4. Hardcoded secrets / SUPABASE_SERVICE_KEY exposure
  5. unsafe Function/eval usage
"""
import os
import re
import sys

ROOT = "web-next/src"


def scan_files():
    for root, _, files in os.walk(ROOT):
        for fn in files:
            if not (fn.endswith(".tsx") or fn.endswith(".ts")):
                continue
            yield os.path.join(root, fn).replace("\\", "/")


def main() -> int:
    # 1. XSS surface
    print("=== 1. dangerouslySetInnerHTML / innerHTML ===")
    xss_hits = []
    for p in scan_files():
        try:
            txt = open(p, encoding="utf-8").read()
        except OSError:
            continue
        for m in re.finditer(r"dangerouslySetInnerHTML|\.innerHTML\s*=", txt):
            ln = txt[: m.start()].count("\n") + 1
            xss_hits.append((p, ln, m.group()))
    if xss_hits:
        for p, ln, k in xss_hits:
            print(f"  ⚠️ {p}:{ln}  ({k})")
    else:
        print("  ✅ None")

    # 2. API routes without auth
    print()
    print("=== 2. API routes missing auth() ===")
    PUBLIC = {"search", "news", "tickers", "macro", "health", "webhook",
              "admin-bootstrap", "robots", "manifest", "sitemap", "ack",
              "issue-session"}
    for p in scan_files():
        if "/api/" not in p or not p.endswith("/route.ts"):
            continue
        try:
            txt = open(p, encoding="utf-8").read()
        except OSError:
            continue
        verbs = re.findall(
            r"export\s+async\s+function\s+(GET|POST|PUT|PATCH|DELETE)\b", txt,
        )
        if not verbs:
            continue
        has_auth = bool(
            re.search(r"\b(auth\(\)|currentUser\(\)|getServerSession|ensureUserId\b)",
                      txt)
        )
        public_intent = any(seg in p for seg in PUBLIC)
        if not has_auth and not public_intent:
            print(f"  ⚠️ {p}: {verbs} — no auth() found")

    # 3. Open redirect — Location headers from req params
    print()
    print("=== 3. Open redirect risk (Location from user input) ===")
    for p in scan_files():
        try:
            txt = open(p, encoding="utf-8").read()
        except OSError:
            continue
        # Look for NextResponse.redirect(...) with a variable that came from
        # search params or req body
        for m in re.finditer(r"NextResponse\.redirect\s*\(\s*([^)]+)\)", txt):
            arg = m.group(1)
            ln = txt[: m.start()].count("\n") + 1
            # Heuristic: ok if arg is a literal string or a known-safe value
            if (arg.startswith('"') or arg.startswith("'") or arg.startswith("`")
                    or arg.startswith("new URL")):
                continue
            print(f"  ⚠️ {p}:{ln}  redirect({arg.strip()[:60]})")

    # 4. Secret leaks — only NEXT_PUBLIC_ prefix should be in client bundle
    print()
    print("=== 4. Secret leak check (SUPABASE_SERVICE_KEY in client modules) ===")
    for p in scan_files():
        try:
            txt = open(p, encoding="utf-8").read()
        except OSError:
            continue
        # Quick check: is this a client module?
        is_client = False
        for line in txt.split("\n"):
            s = line.strip()
            if not s:
                continue
            if s.startswith("//") or s.startswith("*"):
                continue
            is_client = s.startswith('"use client"') or s.startswith("'use client'")
            break
        if is_client and "SUPABASE_SERVICE_KEY" in txt:
            print(f"  🔴 {p}: SERVICE_KEY referenced in 'use client' module!")

    # 5. eval / new Function
    print()
    print("=== 5. eval / new Function ===")
    for p in scan_files():
        try:
            txt = open(p, encoding="utf-8").read()
        except OSError:
            continue
        if re.search(r"\beval\s*\(|new\s+Function\s*\(", txt):
            print(f"  🔴 {p}: dynamic code execution")

    return 0


if __name__ == "__main__":
    os.chdir(os.path.join(os.path.dirname(__file__), ".."))
    sys.exit(main())
