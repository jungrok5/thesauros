"""End-to-end ad-hoc US ticker analysis (Phase 6).

Pipeline:
    1. Cache lookup (us_bars).
    2. If cache miss OR > 1 day stale → fetch from Tiingo + upsert.
    3. Run book pipeline (`app.book.analyzer.analyze_ticker`) on the
       weekly DataFrame.
    4. Return JSON-serialisable dict.

Used by both the CLI smoke test AND the Vercel Python serverless
endpoint (web-next/api/us-analysis.py).
"""
from __future__ import annotations

import sys
from datetime import date
from typing import Any, Dict, Optional

import pandas as pd

from app.book.analyzer import analyze_ticker
from app.data import us_bars_tiingo
from app.db import us_bars_cache


CACHE_STALE_DAYS = 1     # refetch if last_fetched_at older than this


def analyze_us_ticker(ticker: str, force_refresh: bool = False) -> Dict[str, Any]:
    """Analyze a US ticker. Uses cache if fresh, fetches Tiingo if not."""
    ticker_u = ticker.upper().strip()
    if not ticker_u or not ticker_u.replace(".", "").replace("-", "").isalnum():
        raise ValueError(f"invalid ticker: {ticker!r}")

    age = us_bars_cache.cache_age_days(ticker_u)
    needs_fetch = force_refresh or age is None or age >= CACHE_STALE_DAYS

    fetched_now = False
    meta: Dict[str, Any] = {}
    if needs_fetch:
        # Fetch weekly + monthly + meta.
        weekly_rows = us_bars_tiingo.fetch_bars(ticker_u, "W")
        monthly_rows = us_bars_tiingo.fetch_bars(ticker_u, "M")
        try:
            meta = us_bars_tiingo.fetch_ticker_meta(ticker_u)
        except us_bars_tiingo.TiingoError:
            meta = {}
        if not weekly_rows:
            raise us_bars_tiingo.TiingoError(
                f"no weekly bars returned for {ticker_u}"
            )
        # Upsert.
        us_bars_cache.upsert_bars(ticker_u, "W", weekly_rows)
        us_bars_cache.upsert_bars(ticker_u, "M", monthly_rows)
        us_bars_cache.upsert_ticker_meta(
            ticker_u,
            name_en=meta.get("name") or meta.get("ticker") or ticker_u,
            exchange=meta.get("exchangeCode"),
            last_bar_date=date.fromisoformat(weekly_rows[-1]["date"]),
            bars_count=len(weekly_rows),
        )
        fetched_now = True

    # Load weekly from cache → run book pipeline.
    df = us_bars_cache.load_bars(ticker_u, "W")
    if df is None or df.empty:
        raise RuntimeError(f"cache load failed for {ticker_u}")
    # Set grain so analyzer knows we have weekly input.
    df.attrs["grain"] = "W"

    result = analyze_ticker(ticker_u, df, weekly=True, monthly=True)

    return {
        "ticker": ticker_u,
        "fetched_now": fetched_now,
        "cache_age_days": age,
        "bars_count": len(df),
        "first_bar": str(df.iloc[0]["date"].date()),
        "last_bar": str(df.iloc[-1]["date"].date()),
        "meta": {
            "name": meta.get("name") if meta else None,
            "exchange": meta.get("exchangeCode") if meta else None,
            "description": meta.get("description") if meta else None,
        },
        "analysis": _to_jsonable(result),
    }


def _to_jsonable(obj: Any) -> Any:
    """Make analyze_ticker result JSON-serialisable (numpy / dates)."""
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, (pd.Timestamp, date)):
        return obj.isoformat()
    if hasattr(obj, "item"):     # numpy scalars
        try:
            return obj.item()
        except Exception:
            return str(obj)
    return obj


if __name__ == "__main__":
    import json
    if len(sys.argv) < 2:
        print("usage: python -m app.data.us_analyze <TICKER>", file=sys.stderr)
        sys.exit(1)
    try:
        out = analyze_us_ticker(sys.argv[1])
        print(json.dumps(out, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
