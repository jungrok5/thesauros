"""Compute and publish per-ticker chart payloads to Supabase.

Replaces the on-demand FastAPI `/api/book/chart` endpoint. Called from the
daily scan so the site can render charts directly from `chart_data`
without any backend HTTP hop.

Payload schema (identical to what the FastAPI endpoint used to return):
  - bars:        [{t, open, high, low, close, volume}]
  - mas:         {ma_10, ma_20, ma_60, ma_120, ma_240}
  - patterns:    completed only, with kind/direction/confidence/entry/stop/target
  - quarter_lines: 4-quadrant lines from most-recent 장대양봉
  - last_candle: latest candle summary
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.book.analyzer import load_ticker_data              # noqa: E402
from app.book.trend import resample_to_period               # noqa: E402
from app.book.patterns import detect_all                    # noqa: E402
from app.book.candles import latest_candle_summary          # noqa: E402
from app.db import get_conn                                 # noqa: E402

log = logging.getLogger("publish_chart")

TIMEFRAMES = ("daily", "weekly", "monthly")
WARMUP = {"daily": 1, "weekly": 5, "monthly": 20}


def build_chart_payload(ticker: str, timeframe: str, years: int = 2) -> Optional[Dict[str, Any]]:
    """Return the chart JSON or None if no data."""
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"bad timeframe: {timeframe}")

    df = load_ticker_data(ticker, years=years + WARMUP[timeframe])
    if df is None or df.empty:
        return None

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    if timeframe == "weekly":
        rsr = resample_to_period(df, "W")
        df = rsr.reset_index().rename(columns={rsr.index.name or "index": "date"})
        if "date" not in df.columns:
            df = df.rename(columns={df.columns[0]: "date"})
    elif timeframe == "monthly":
        rsr = resample_to_period(df, "M")
        df = rsr.reset_index().rename(columns={rsr.index.name or "index": "date"})
        if "date" not in df.columns:
            df = df.rename(columns={df.columns[0]: "date"})

    if years and len(df) > 0:
        cutoff = df["date"].iloc[-1] - pd.Timedelta(days=int(years * 365.25))
        visible_mask = df["date"] >= cutoff
    else:
        visible_mask = pd.Series(True, index=df.index)

    df_vis = df[visible_mask].reset_index(drop=True)
    bars = [
        {
            "t": int(pd.Timestamp(d).timestamp()),
            "open": float(o), "high": float(h), "low": float(lo),
            "close": float(c), "volume": int(v) if pd.notna(v) else 0,
        }
        for d, o, h, lo, c, v in zip(
            df_vis["date"], df_vis["open"], df_vis["high"], df_vis["low"],
            df_vis["close"], df_vis["volume"],
        )
        if pd.notna(o) and pd.notna(c)
    ]

    closes_full = df["close"].astype(float)
    dates_full = df["date"]
    mas: Dict[str, List[Dict[str, Any]]] = {}
    for w in (10, 20, 60, 120, 240):
        if len(closes_full) >= w:
            ma = closes_full.rolling(w).mean()
            mas[f"ma_{w}"] = [
                {"t": int(pd.Timestamp(d).timestamp()), "value": float(v)}
                for d, v, vis in zip(dates_full, ma, visible_mask)
                if pd.notna(v) and vis
            ]

    patterns: List[Dict[str, Any]] = []
    for p in detect_all(df_vis):
        pd_ = p.to_dict()
        if pd_.get("completed"):
            patterns.append({
                "kind": pd_["kind"],
                "direction": pd_["direction"],
                "confidence": pd_["confidence"],
                "entry": pd_.get("entry"),
                "stop": pd_.get("stop"),
                "target": pd_.get("target"),
                "extra": pd_.get("extra"),
                "detected_at": pd_.get("detected_at"),
            })

    quarter_lines = None
    if len(df_vis) >= 2:
        for i in range(len(df_vis) - 1, max(-1, len(df_vis) - 30), -1):
            o, c, hi, lo = (df_vis.iloc[i].get(k) for k in ("open", "close", "high", "low"))
            try:
                o, c, hi, lo = float(o), float(c), float(hi), float(lo)
            except Exception:
                continue
            if o <= 0:
                continue
            body_pct = (c - o) / o
            if body_pct >= 0.05 and c > o:
                quarter_lines = {
                    "price_low": o, "price_25": o + 0.25 * (c - o),
                    "price_50": o + 0.50 * (c - o), "price_75": o + 0.75 * (c - o),
                    "price_high": c,
                    "candle_t": int(pd.Timestamp(df_vis.iloc[i]["date"]).timestamp()),
                }
                break

    last_candle = latest_candle_summary(df_vis)

    return {
        "ticker": ticker,
        "timeframe": timeframe,
        "bars": bars,
        "mas": mas,
        "patterns": patterns,
        "quarter_lines": quarter_lines,
        "last_candle": last_candle,
    }


def upsert_chart(ticker: str, timeframe: str, years: int, payload: Dict[str, Any]) -> None:
    payload_json = json.dumps(payload, ensure_ascii=False, default=str)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chart_data (ticker, timeframe, years, payload, updated_at)
                VALUES (%s, %s, %s, %s::jsonb, now())
                ON CONFLICT (ticker, timeframe, years) DO UPDATE SET
                  payload = EXCLUDED.payload, updated_at = now()
                """,
                (ticker, timeframe, years, payload_json),
            )


def publish_for(ticker: str, timeframes: Iterable[str] = TIMEFRAMES,
                years: int = 2) -> Dict[str, int]:
    """Build and upsert chart payloads for one ticker across timeframes."""
    stats = {"upserts": 0, "skipped_no_data": 0}
    for tf in timeframes:
        payload = build_chart_payload(ticker, tf, years=years)
        if payload is None:
            stats["skipped_no_data"] += 1
            continue
        upsert_chart(ticker, tf, years, payload)
        stats["upserts"] += 1
    return stats


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--ticker", required=True)
    p.add_argument("--timeframes", nargs="+", default=list(TIMEFRAMES))
    p.add_argument("--years", type=int, default=2)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    s = publish_for(args.ticker, args.timeframes, args.years)
    log.info("done: %s", s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
