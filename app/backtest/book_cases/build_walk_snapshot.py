"""Regenerate the walk-result snapshot for a book-case fixture.

Walks the fixture through analyze_ticker bar-by-bar, then saves the
{date → [signals]} map to `fixtures/<slug>.walk.json` (tracked).

Tests load the snapshot directly (fast). Re-run this CLI whenever:
  - the analyzer changes (new pattern detector, threshold tune, etc.),
  - a fixture is updated.

The diff of the snapshot file in the resulting PR is the human-
reviewable form of "what changed in our signal flow on this case".

Usage:
    python -m app.backtest.book_cases.build_walk_snapshot \\
        --fixture 035720_kakao_2019_2021_double_top
"""
from __future__ import annotations

import argparse
import logging
import sys

from app.backtest.book_cases.walk_forward import (
    load_fixture, walk, save_walk_snapshot,
)

log = logging.getLogger("backtest.book_cases.build_walk_snapshot")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fixture", required=True,
                   help="fixture slug, e.g. 035720_kakao_2019_2021_double_top")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    fx = load_fixture(args.fixture)
    log.info("walking %s (%s → %s)…",
             fx["ticker"], fx["start"], fx["end"])
    result = walk(fx)
    out = save_walk_snapshot(result, args.fixture)
    n_signals = sum(len(v) for v in result.values())
    log.info("wrote %s — %d bars with signals, %d signals total",
             out.name, len(result), n_signals)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
