"""Performance audit — page query patterns, missing limits, N+1, cache strategy."""
import os
import re
import sys

ROOT = "web-next/src"


def scan_files():
    for root, _, files in os.walk(ROOT):
        for fn in files:
            if not (fn.endswith(".ts") or fn.endswith(".tsx")):
                continue
            yield os.path.join(root, fn).replace("\\", "/")


def main() -> int:
    # 1. PostgREST .in().order() without .limit()
    print("=== 1. PostgREST .in().order() without .limit() ===")
    n = 0
    for p in scan_files():
        try:
            txt = open(p, encoding="utf-8").read()
        except OSError:
            continue
        # Find any sb chain with .in(...) and .order(...) somewhere
        for m in re.finditer(
            r"\.from\([^)]+\)[\s\S]{0,800}?\.in\(", txt
        ):
            start = m.start()
            # Find the end of this query chain (next semicolon or closing bracket
            # at indentation lower than chain's). Simpler: check next 600 chars.
            chunk = txt[start: start + 1200]
            if ".order(" in chunk and ".limit(" not in chunk:
                ln = txt[:start].count("\n") + 1
                # Skip if it's an .insert() or .update() (not affected)
                if ".insert(" in chunk[:200] or ".update(" in chunk[:200]:
                    continue
                # Skip false positives like .ins(): only flag chains where
                # .in is on its own line / separated word boundary
                n += 1
                if n <= 12:
                    print(f"  WARN {p}:{ln}")
    if n == 0:
        print("  OK: all .in() chains include explicit .limit()")
    elif n > 12:
        print(f"  ... +{n - 12} more")

    # 2. N+1 — await inside for/while loops over sb.from
    print()
    print("=== 2. N+1 (await sb.from inside loop) ===")
    n = 0
    for p in scan_files():
        try:
            txt = open(p, encoding="utf-8").read()
        except OSError:
            continue
        # Crude: find for/while that contains both await and sb.from
        for m in re.finditer(
            r"\b(for|while)\s*\([^{]*\)\s*\{[\s\S]{0,500}?await\s+sb\.from",
            txt,
        ):
            ln = txt[: m.start()].count("\n") + 1
            n += 1
            if n <= 8:
                print(f"  WARN {p}:{ln}")
    if n == 0:
        print("  OK: no N+1 patterns")

    # 3. force-dynamic without auth dep
    print()
    print("=== 3. force-dynamic without auth (could ISR) ===")
    n = 0
    for p in scan_files():
        if not p.endswith("/page.tsx"):
            continue
        try:
            txt = open(p, encoding="utf-8").read()
        except OSError:
            continue
        if "force-dynamic" not in txt:
            continue
        if any(k in txt for k in ("auth()", "ensureUserId", "session?.user")):
            continue
        n += 1
        print(f"  INFO {p} — force-dynamic but no auth dep (could ISR)")
    if n == 0:
        print("  OK: all force-dynamic pages are auth-gated")

    # 4. Large select * patterns
    print()
    print("=== 4. select(\"*\") on potentially large tables ===")
    n = 0
    for p in scan_files():
        try:
            txt = open(p, encoding="utf-8").read()
        except OSError:
            continue
        for m in re.finditer(r"\.from\([\"'](\w+)[\"']\)[\s\S]{0,80}?\.select\([\"']\*[\"']\)", txt):
            tbl = m.group(1)
            if tbl in ("bars", "scan_results", "investor_flow", "disclosures",
                       "fundamentals", "macro_series", "alerts"):
                ln = txt[: m.start()].count("\n") + 1
                n += 1
                print(f"  WARN {p}:{ln}  select(*) from {tbl}")
    if n == 0:
        print("  OK: no select(*) on large tables")

    # 5. Cache strategy — revalidate on page.tsx
    print()
    print("=== 5. Cache strategy summary ===")
    by_strategy = {"dynamic": 0, "static": 0, "revalidate": 0, "default": 0}
    for p in scan_files():
        if not p.endswith("/page.tsx"):
            continue
        try:
            txt = open(p, encoding="utf-8").read()
        except OSError:
            continue
        if "force-dynamic" in txt:
            by_strategy["dynamic"] += 1
        elif "force-static" in txt:
            by_strategy["static"] += 1
        elif "revalidate" in txt:
            by_strategy["revalidate"] += 1
        else:
            by_strategy["default"] += 1
    for k, v in by_strategy.items():
        print(f"  {k:<12} {v}")

    return 0


if __name__ == "__main__":
    os.chdir(os.path.join(os.path.dirname(__file__), ".."))
    sys.exit(main())
