"""Recover the book transcripts + chart JSONs from the Claude session log.

A `git filter-repo` purged book_images/ from history (copyright cleanup,
commit 1d61920). The transcripts/charts files were never committed in
the first place — but the user generated them earlier in this session
via the Write tool, so the JSONL session log holds the full content of
every write.

This script walks the JSONL, finds Write tool invocations targeting
`book_images/.../{transcripts,charts}/*.{md,json}`, and re-creates the
files on disk. Idempotent — overwrites with the latest version if a
file was rewritten multiple times.

Usage:
    python scripts/restore_book_transcripts.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

SESSION_LOG = Path(
    r"C:\Users\jungrok5\.claude\projects\c--Project-finance"
    r"\5acb3dc0-b643-4179-bd75-9068535e87b1.jsonl"
)
ROOT = Path(__file__).resolve().parents[1]


def is_target_path(p: str) -> bool:
    """File belongs to book_images/transcripts or book_images/charts or
    is a top-level SUMMARY_*.md."""
    p = p.replace("/", "\\")
    if "book_images\\" not in p:
        return False
    if "\\transcripts\\" in p and p.endswith(".md"):
        return True
    if "\\charts\\" in p and p.endswith(".json"):
        return True
    if "\\SUMMARY_" in p and p.endswith(".md"):
        return True
    return False


def normalize_path(raw: str) -> Optional[Path]:
    """Take an absolute path string from the JSONL and re-root it under
    the local project root (so it works even if the absolute path in the
    log was written from a different machine/checkout)."""
    s = raw.replace("/", os.sep).replace("\\", os.sep)
    idx = s.find("book_images" + os.sep)
    if idx == -1:
        return None
    rel = s[idx:]
    return ROOT / rel


def iter_tool_writes(log_path: Path):
    """Yield (file_path, content) for every Write tool invocation."""
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Walk message content; tool_use blocks have name + input
            msg = rec.get("message") or {}
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_use":
                    continue
                if block.get("name") not in ("Write",):
                    continue
                inp = block.get("input") or {}
                fp = inp.get("file_path")
                ct = inp.get("content")
                if not isinstance(fp, str) or not isinstance(ct, str):
                    continue
                yield fp, ct


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    if not SESSION_LOG.exists():
        print(f"session log not found: {SESSION_LOG}", file=sys.stderr)
        return 1

    # Collect latest content per path (last-write-wins, mirroring how
    # the file ended up on disk back when it was created).
    latest: dict[Path, tuple[str, int]] = {}
    seen = 0
    for raw_path, content in iter_tool_writes(SESSION_LOG):
        if not is_target_path(raw_path):
            continue
        seen += 1
        norm = normalize_path(raw_path)
        if norm is None:
            continue
        # version counter so we can report rewrites
        prev = latest.get(norm, ("", 0))
        latest[norm] = (content, prev[1] + 1)

    if not latest:
        print("no recoverable files matched in session log.")
        return 0

    by_kind: dict[str, int] = {}
    for path in latest:
        kind = (
            "transcripts" if "transcripts" in path.parts
            else "charts" if "charts" in path.parts
            else "SUMMARY"
        )
        by_kind[kind] = by_kind.get(kind, 0) + 1
    print(f"found {len(latest)} unique files (from {seen} Write events)")
    for k, v in sorted(by_kind.items()):
        print(f"  {k:12} {v} files")

    if args.dry_run:
        print("--dry-run: not writing anything.")
        return 0

    written = 0
    skipped_unchanged = 0
    for path, (content, n_versions) in sorted(latest.items()):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = path.read_text(encoding="utf-8", errors="replace")
            if existing == content:
                skipped_unchanged += 1
                continue
        path.write_text(content, encoding="utf-8")
        written += 1
        if args.verbose:
            print(f"  wrote {path.relative_to(ROOT)} (v{n_versions})")

    print(f"wrote {written} files · {skipped_unchanged} already present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
