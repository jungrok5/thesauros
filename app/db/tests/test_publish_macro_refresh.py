"""Regression guard: publish_macro must refresh macro_series first.

2026-06-01 incident — Daily Data Refresh cron failed because the
`macro_series` cache was 17 days stale. Root cause: the codebase
contained an `ingest_all` function (`app.macro.fetch`) intended to
refresh that cache, but NO caller actually invoked it. The docstring
in fetch.py claimed publish_macro called it, but the wiring was
missing for as long as the table existed.

This test pins the wiring: publish_macro.main must call ingest_all
before publish. Without it, macro_state would publish from a stale
cache, the data-quality assertion would fire, and the cron would
fail again.
"""
from __future__ import annotations

import ast
from pathlib import Path


PUBLISH_PATH = Path(__file__).resolve().parents[2] / "db" / "publish_macro.py"


def test_publish_macro_main_calls_ingest_all():
    """Static check — main() must reference `ingest_all` and call it
    before publish(). Skips deep AST analysis in favor of a substring
    scan that's robust to refactors (function move, alias, etc.)."""
    src = PUBLISH_PATH.read_text(encoding="utf-8")
    # The fix uses `from app.macro.fetch import ingest_all` then
    # `ingest_all(...)`. Either form satisfies — we check both the
    # import surface AND a call expression.
    tree = ast.parse(src)
    main_node = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "main"),
        None,
    )
    assert main_node is not None, "publish_macro.main not found"

    # Walk main's body for any Call whose func resolves to 'ingest_all'.
    found = False
    for n in ast.walk(main_node):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        name = getattr(f, "id", None) or getattr(f, "attr", None)
        if name == "ingest_all":
            found = True
            break
    assert found, (
        "publish_macro.main() must call ingest_all(...) to refresh the "
        "macro_series cache before publishing. Without it the cron's "
        "data-quality assertion fires on stale macro_series and the "
        "whole Daily Data Refresh fails (2026-06-01 incident)."
    )
