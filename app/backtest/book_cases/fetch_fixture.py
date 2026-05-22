"""Pull a historical W + M bar fixture for one KR ticker.

Reuses `app.db.ingest_bars.fetch_kr_ticker` (FDR daily → resampled W +
M) and writes the result to `fixtures/<slug>.json`. Tracked in git so
book-case OOS tests run deterministically in CI without external HTTP.

Usage:
    python -m app.backtest.book_cases.fetch_fixture 035720.KS \\
        --start 2018-01-01 --end 2022-06-30 \\
        --slug kakao_2019_2021_double_top

Output:
    app/backtest/book_cases/fixtures/035720_kakao_2019_2021_double_top.json
    {
      "ticker": "035720.KS",
      "start": "2018-01-01",
      "end":   "2022-06-30",
      "fetched_at": "2026-05-22T...",
      "bars": [
        {"granularity": "W", "date": "2018-01-05", "open":..., "high":..., ...},
        ...
      ]
    }

Why fixture, not live DB:
  - DB `bars` table retains only ~2 years (240MA needs 144 weeks). Book
    cases reach 5+ years back → must snapshot once.
  - Frozen fixture = deterministic test. If FDR changes data, we see
    the diff in PR review, not as a silent test flake.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Tuple, Any

from app.db.ingest_bars import fetch_kr_ticker

log = logging.getLogger("backtest.fetch_fixture")

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def fetch_to_fixture(
    ticker: str, start: date, end: date, slug: str | None = None,
) -> Path:
    """Pull bars for one ticker and write to fixtures/<slug>.json.

    Returns the path written. Overwrites any existing file.
    """
    rows: List[Tuple[Any, ...]] = fetch_kr_ticker(ticker, start, end)
    if not rows:
        raise RuntimeError(
            f"FDR returned no rows for {ticker} {start}→{end} — "
            "ticker may be invalid or out of FDR's range."
        )
    # rows = (ticker, granularity, date, open, high, low, close, adj_close, volume)
    bars = [
        {
            "granularity": g,
            "date": d.isoformat(),
            "open": o, "high": h, "low": lo, "close": c,
            "adj_close": ac, "volume": v,
        }
        for (_t, g, d, o, h, lo, c, ac, v) in rows
    ]
    payload = {
        "ticker": ticker,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "bars": bars,
    }
    _FIXTURE_DIR.mkdir(exist_ok=True)
    code = ticker.split(".")[0]
    name = f"{code}_{slug}.json" if slug else f"{code}.json"
    out = _FIXTURE_DIR / name
    with out.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    log.info(
        "wrote %s (%d bars: %d W + %d M)",
        out.name, len(bars),
        sum(1 for b in bars if b["granularity"] == "W"),
        sum(1 for b in bars if b["granularity"] == "M"),
    )
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("ticker", help="e.g. 035720.KS")
    p.add_argument("--start", required=True, help="ISO date")
    p.add_argument("--end", required=True, help="ISO date")
    p.add_argument("--slug", default=None,
                   help="filename suffix, e.g. kakao_2019_2021_double_top")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    sd = date.fromisoformat(args.start)
    ed = date.fromisoformat(args.end)
    out = fetch_to_fixture(args.ticker, sd, ed, slug=args.slug)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
