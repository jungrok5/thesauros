"""Static analyzer: find server modules that import runtime
(non-React-component) values from "use client" modules.

Why it matters: Next.js's React Server Components contract says a
client-marked module can export components for server use, but its
sibling utility exports become unsafe to import server-side — they
get inlined into a client-only bundle and the server resolver
either errors at runtime or silently breaks (Vercel deployments
show this as ERROR <numeric ID>).

Bug seen 2026-05-20: app/(app)/watchlist/page.tsx imported
`groupColorClass` (a plain string-returning helper) from
group-manager-client.tsx (which has "use client"). Production
crashed; local dev tolerated it. Fixed by moving the helper to
group-colors.ts.

Usage: python scripts/find_client_module_imports.py
Exits with code 1 if any violations found (CI gate).
"""
from __future__ import annotations

import os
import re
import sys

# We only care about web-next/src — other roots have no Next.js
# server/client distinction.
ROOT = os.path.join(os.path.dirname(__file__), "..", "web-next", "src")


def is_client_module(path: str) -> bool:
    """Treat a file as a client module iff its FIRST non-comment,
    non-empty line is "use client" or 'use client'."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                # rudimentary comment skip — single-line // only.
                # Block comments at top of file are rare.
                if s.startswith("//") or s.startswith("/*") or s.startswith("*"):
                    continue
                return (
                    s.startswith('"use client"') or s.startswith("'use client'")
                )
    except OSError:
        pass
    return False


def normalize_module(path: str) -> str:
    """src/foo/bar.tsx → foo/bar (the path part used in '@/foo/bar' imports
    and in '../bar' relative imports' basename matching)."""
    rel = os.path.relpath(path, ROOT).replace("\\", "/")
    return rel.rsplit(".", 1)[0]


def import_names_from(text: str, basename: str) -> list[str]:
    """Returns list of non-type, non-PascalCase names imported from a
    module whose basename appears at end of the import path."""
    # Match `import { … } from "path/basename"` where "type" prefix is
    # legal but we strip it.
    pattern = re.compile(
        r"import\s*(?:type\s*)?\{([^}]+)\}\s*from\s*[\"'][^\"']*"
        + re.escape(basename) + r"[\"']"
    )
    out: list[str] = []
    for m in pattern.finditer(text):
        for raw in m.group(1).split(","):
            name = raw.strip()
            if not name:
                continue
            # `type X` inside a non-type-only block — still a type import
            if name.startswith("type "):
                continue
            # PascalCase = component (allowed to cross the boundary)
            if name and name[0].isupper():
                continue
            # Strip `name as alias` to just `name` for reporting
            display = name.split(" as ")[0].strip()
            out.append(display)
    return out


def main() -> int:
    if not os.path.isdir(ROOT):
        print(f"ROOT not found: {ROOT}")
        return 2

    # 1. Collect every client module path → basename
    client_modules: dict[str, str] = {}  # normalized path → basename
    for root, _, files in os.walk(ROOT):
        for fn in files:
            if not (fn.endswith(".tsx") or fn.endswith(".ts")):
                continue
            p = os.path.join(root, fn)
            if is_client_module(p):
                norm = normalize_module(p)
                client_modules[norm] = norm.split("/")[-1]

    # 2. For each non-client module, look for imports of any non-component
    #    name from a client module.
    violations: list[tuple[str, str, list[str]]] = []
    for root, _, files in os.walk(ROOT):
        for fn in files:
            if not (fn.endswith(".tsx") or fn.endswith(".ts")):
                continue
            p = os.path.join(root, fn)
            if is_client_module(p):
                continue
            try:
                txt = open(p, encoding="utf-8").read()
            except OSError:
                continue
            for client_path, basename in client_modules.items():
                if basename not in txt:
                    continue
                names = import_names_from(txt, basename)
                if names:
                    violations.append((
                        os.path.relpath(p, ROOT).replace("\\", "/"),
                        client_path,
                        names,
                    ))

    if not violations:
        print("OK: no server module imports runtime non-component "
              "values from a 'use client' module.")
        return 0

    print(
        "ERROR: server module imports runtime non-component values "
        "from a client module — "
        "this triggers Vercel runtime errors (see ERROR 1025776953, 2026-05-20).\n"
    )
    for server, client, names in violations:
        print(f"  {server}")
        print(f"    imports {names} from client module {client}")
        print(f"    fix: move those exports to a sibling .ts (no 'use client').")
    return 1


if __name__ == "__main__":
    sys.exit(main())
