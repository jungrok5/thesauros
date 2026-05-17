"""Daily book-rule scan → Supabase scan_results.

For every active ticker that has at least N years of daily bars locally,
run the book analyzer and publish the *active* (recently completed) signals
to the `scan_results` table.

Strategy:
  • READ bars from local DuckDB (pit_db) — already populated by ingest_*.
    Falls back to yfinance for tickers missing locally (covered by Phase 2
    ingest expansion).
  • RUN app.book.analyzer.analyze_ticker(ticker, df) — single-shot pipeline.
  • EXTRACT triggered signals into scan_results rows of (signal_type,
    timeframe, detected_at, strength, reason, params).
  • UPSERT: replace any prior active row for the same (ticker, signal_type,
    timeframe) → only the latest detection is kept active.

Usage:
    python -m app.db.scan_daily --markets KOSPI KOSDAQ NASDAQ
    python -m app.db.scan_daily --tickers 005930.KS 035720.KS
    python -m app.db.scan_daily --limit 50          # quick sample
    python -m app.db.scan_daily --years 5           # 기본; 책 240MA 위해 최소 2년
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.book.analyzer import analyze_ticker, load_ticker_data    # noqa: E402
from app.db import get_conn                                       # noqa: E402

log = logging.getLogger("scan_daily")


# Map book detection → scan_results.signal_type
SIGNAL_TYPE_MAP = {
    # action (overall) — useful for "top recommendation" filter
    "STRONG_BUY":    ("action_strong_buy",   0.85),
    "BUY":           ("action_buy",          0.70),
    "SELL":          ("action_sell",         0.70),
    "SELL_OR_SHORT": ("action_sell_short",   0.80),
    "AVOID":         ("action_avoid",        0.70),
}

# Korean pattern/signal name → ASCII slug (canonical, stable across UI/queries).
PATTERN_SLUG_MAP = {
    "쌍바닥":          "double_bottom",
    "쌍봉":            "double_top",
    "H&S":            "head_and_shoulders",
    "헤드앤숄더":      "head_and_shoulders",
    "역H&S":          "inverse_head_and_shoulders",
    "역헤드앤숄더":    "inverse_head_and_shoulders",
    "삼중바닥":        "triple_bottom",
    "삼고점":          "triple_top",
    "원형천장":        "rounding_top",
    "원형바닥":        "rounding_bottom",
    "컵앤핸들":        "cup_and_handle",
    "Cup with Handle": "cup_and_handle",
    "겹쌍봉":          "double_double_top",
    "겹쌍바닥":        "double_double_bottom",
    "대쌍봉":          "big_double_top",
    "대쌍바닥":        "big_double_bottom",
    "포킹":            "forking",
    "돌반지":          "doulbanji",
    "240MA 돌파":      "ma240_breakout",
    "후킹":            "hooking",
    "펌핑":            "pumping",
    "랠리":            "rally",
    "저승사자":        "death_messenger",
    # reversals
    "1패턴":           "type1_same",
    "2패턴":           "type2_cross",
    "3패턴":           "type3_single_candle",
    "4패턴":           "type4_wedge_convergence",
    "동종 패턴":       "type1_same",
    "이종 패턴":       "type2_cross",
    "쐐기 수렴":       "type4_wedge_convergence",
    # volume cases
    "바닥+거래량3배": "vol_bottom_3x",
    "급등초기거래량증가": "vol_surge_early",
    "상투거래량감소":  "vol_top_drying",
    "역매집":          "reverse_accumulation",
}


def _slug(name: str, fallback: str) -> str:
    """Korean / mixed name → ASCII slug. Uses PATTERN_SLUG_MAP first."""
    if not name:
        return fallback
    if name in PATTERN_SLUG_MAP:
        return PATTERN_SLUG_MAP[name]
    # try partial match (e.g. "쌍바닥 (W자형, 짝궁뎅이)" → "double_bottom")
    for key, slug in PATTERN_SLUG_MAP.items():
        if key in name:
            return slug
    # last resort: keep only ASCII
    slug = "".join(c if (c.isalnum() or c in "_-") else "_"
                   for c in name.lower())
    slug = "_".join(p for p in slug.split("_") if p)
    return slug if slug.isascii() and slug else fallback


def _action_signal(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    action = result.get("action")
    if not action or action == "HOLD":
        return None
    info = SIGNAL_TYPE_MAP.get(action)
    if not info:
        return None
    stype, base_strength = info
    book_score = float(result.get("book_score") or 0)
    strength = min(1.0, max(0.0, abs(book_score) * 0.4 + base_strength * 0.6))
    return {
        "signal_type": stype,
        "timeframe": "daily",
        "strength": round(strength, 3),
        "reason": f"{action} (book_score={book_score:+.2f})",
        "params": {
            "book_score": book_score,
            "trend_signal": result.get("trend", {}).get("book_signal"),
            "last_close": result.get("last_close"),
        },
    }


def _pattern_signals(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Patterns from daily/weekly/monthly that are *completed* in the latest bars."""
    out: List[Dict[str, Any]] = []
    for p in result.get("patterns", []):
        if not p.get("completed"):
            continue
        kind = p.get("kind") or p.get("name") or "pattern"
        direction = p.get("direction") or "neutral"
        confidence = float(p.get("confidence") or 0.5)
        tf = p.get("timeframe", "daily")
        # signal_type uses the romanised slug so it's stable across UI
        slug_ascii = _slug(kind, "pattern")
        out.append({
            "signal_type": f"pattern_{slug_ascii}",
            "timeframe": tf,
            "strength": round(confidence, 3),
            "reason": f"{kind} 완성 (신뢰도 {confidence:.2f}, {direction})",
            "params": {
                "kind": kind, "direction": direction,
                "confidence": confidence, "timeframe": tf,
            },
        })
    return out


def _reversal_signals(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in result.get("reversals", []):
        if not r.get("completed"):
            continue
        kind = r.get("kind") or r.get("name") or "reversal"
        confidence = float(r.get("confidence") or 0.5)
        direction = r.get("direction") or "neutral"
        slug = _slug(kind, "reversal")
        out.append({
            "signal_type": f"retracement_{slug}",
            "timeframe": "daily",
            "strength": round(confidence, 3),
            "reason": f"되돌림 {kind} 완성 ({direction})",
            "params": {"kind": kind, "direction": direction, "confidence": confidence},
        })
    return out


def _volume_signals(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    vc = result.get("volume_case")
    if vc and vc.get("confidence", 0) >= 0.6:
        # volume_case format: {case:int, label_kr:str, direction, confidence, reason}
        case_no = vc.get("case")
        label = vc.get("label_kr") or vc.get("kind") or vc.get("name", "volume")
        direction = vc.get("direction") or "neutral"
        slug = f"case_{case_no}" if case_no else _slug(label, "vol")
        out.append({
            "signal_type": f"volume_{slug}",
            "timeframe": "daily",
            "strength": round(float(vc["confidence"]), 3),
            "reason": f"거래량 {label} ({direction})",
            "params": {"case": case_no, "label": label, "direction": direction,
                       "confidence": float(vc["confidence"]),
                       "reason": vc.get("reason")},
        })
    ra = result.get("reverse_accumulation")
    if ra and ra.get("detected"):
        out.append({
            "signal_type": "reverse_accumulation",
            "timeframe": "daily",
            "strength": round(float(ra.get("confidence", 0.7)), 3),
            "reason": "역매집 캔들 반복 (심봤다)",
            "params": ra,
        })
    return out


def extract_signals(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """All signals worth publishing for one ticker."""
    signals = []
    a = _action_signal(result)
    if a:
        signals.append(a)
    signals.extend(_pattern_signals(result))
    signals.extend(_reversal_signals(result))
    signals.extend(_volume_signals(result))
    return signals


def _list_tickers(markets: Optional[List[str]] = None,
                  tickers: Optional[List[str]] = None,
                  limit: Optional[int] = None) -> List[str]:
    """Pick tickers from `tickers` master table."""
    where = "is_active = true"
    params: List[Any] = []
    if tickers:
        where += " AND ticker = ANY(%s)"
        params.append(list(tickers))
    elif markets:
        where += " AND market = ANY(%s)"
        params.append([m.upper() for m in markets])
    sql = f"SELECT ticker FROM tickers WHERE {where} ORDER BY ticker"
    if limit:
        sql += f" LIMIT {int(limit)}"
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [r[0] for r in cur.fetchall()]


def _flush_chunk(chunk: List[Dict[str, Any]]) -> int:
    """Write a chunk of (ticker, as_of, signals) results in one transaction.

    Two SQL statements per chunk (vs. 2 per ticker in the old per-ticker
    pattern): a single bulk UPDATE deactivates all current rows for the
    chunk's tickers, then a single executemany INSERT writes the new
    signal rows.
    """
    import json
    if not chunk:
        return 0
    tickers = [c["ticker"] for c in chunk]
    rows: List[Tuple[Any, ...]] = []
    for c in chunk:
        for s in c["signals"]:
            rows.append((
                c["ticker"], s["signal_type"], s["timeframe"],
                c["as_of"], s.get("strength", 0.5),
                s.get("reason"),
                json.dumps(s.get("params") or {}, ensure_ascii=False),
            ))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE scan_results SET is_active = false "
                "WHERE ticker = ANY(%s) AND is_active = true",
                (tickers,),
            )
            if rows:
                cur.executemany(
                    """
                    INSERT INTO scan_results
                      (ticker, signal_type, timeframe, detected_at,
                       strength, reason, params)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    rows,
                )
    return len(rows)


def scan_one_local(ticker: str, years: int = 5) -> Dict[str, Any]:
    """Compute the scan result for one ticker without touching the DB.

    Returns: {ticker, status, as_of?, signals?, result?}
      status ∈ {"ok", "insufficient_history", "no_active_signal"}
      `result` is the full analyze_ticker() output (used to populate
      analyze_results so the site can render without FastAPI).
    """
    df = load_ticker_data(ticker, years=years)
    if df is None or len(df) < 250:
        return {"ticker": ticker, "status": "insufficient_history"}
    result = analyze_ticker(ticker, df)
    signals = extract_signals(result)
    base = {
        "ticker": ticker,
        "as_of": pd.Timestamp(result.get("as_of")),
        "result": result,
    }
    if not signals:
        return {**base, "status": "no_active_signal"}
    return {**base, "status": "ok", "signals": signals}


def _flush_analyze_chunk(chunk: List[Dict[str, Any]]) -> int:
    """Upsert full analyze_ticker() outputs into analyze_results."""
    import json
    rows: List[Tuple[Any, ...]] = []
    for c in chunk:
        result = c.get("result")
        if not result:
            continue
        as_of = pd.Timestamp(result.get("as_of")).date()
        rows.append((
            c["ticker"],
            as_of,
            float(result.get("last_close") or 0),
            result.get("action"),
            float(result.get("book_score") or 0),
            json.dumps(result, ensure_ascii=False, default=str),
        ))
    if not rows:
        return 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO analyze_results
                  (ticker, as_of, last_close, action, book_score, result, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, now())
                ON CONFLICT (ticker) DO UPDATE SET
                  as_of = EXCLUDED.as_of,
                  last_close = EXCLUDED.last_close,
                  action = EXCLUDED.action,
                  book_score = EXCLUDED.book_score,
                  result = EXCLUDED.result,
                  updated_at = now()
                """,
                rows,
            )
    return len(rows)


def _publish_chart_for(tickers: Iterable[str]) -> int:
    """Build + upsert chart payloads for each ticker across daily/weekly/monthly.

    Same precompute pattern as analyze_results — keeps the site
    backend-free.
    """
    from app.db.publish_chart import publish_for
    n = 0
    for t in tickers:
        try:
            s = publish_for(t)
            n += s.get("upserts", 0)
        except Exception as e:                           # noqa: BLE001
            log.warning("chart publish failed for %s: %s", t, e)
    return n


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--markets", nargs="+", default=None,
                   help="filter by market (KOSPI / KOSDAQ / NASDAQ)")
    p.add_argument("--tickers", nargs="+", default=None,
                   help="explicit ticker list (overrides --markets)")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--years", type=int, default=5)
    p.add_argument("--batch", type=int, default=100,
                   help="flush DB rows every N tickers (default 100)")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    tickers = _list_tickers(markets=args.markets,
                            tickers=args.tickers,
                            limit=args.limit)
    log.info("scanning %d tickers (years=%d, batch=%d)",
             len(tickers), args.years, args.batch)
    t0 = time.time()
    stats = {"scanned": 0, "with_signals": 0, "inserted": 0,
             "analyze_upserted": 0, "chart_upserted": 0,
             "skipped_no_history": 0, "skipped_no_signal": 0, "errors": 0}
    chunk: List[Dict[str, Any]] = []
    # Tickers with no active signal — still get the full analyze result
    # stored so the /stocks/[ticker] page can render their trend/candles.
    no_signal_chunk: List[Dict[str, Any]] = []

    def flush() -> None:
        nonlocal chunk, no_signal_chunk
        if chunk or no_signal_chunk:
            # Deactivate "no signal today" tickers via empty-signals rows.
            all_for_scan = chunk + [
                {"ticker": c["ticker"], "as_of": pd.Timestamp.now(), "signals": []}
                for c in no_signal_chunk
            ]
            stats["inserted"] += _flush_chunk(all_for_scan)
            # Both buckets carry `result` from analyze_ticker — store both.
            stats["analyze_upserted"] += _flush_analyze_chunk(
                chunk + no_signal_chunk
            )
            # Also pre-render the chart payload (daily/weekly/monthly) so
            # /stocks/[ticker] can render without FastAPI.
            stats["chart_upserted"] += _publish_chart_for(
                [c["ticker"] for c in (chunk + no_signal_chunk)]
            )
        chunk = []
        no_signal_chunk = []

    for i, t in enumerate(tickers, 1):
        try:
            res = scan_one_local(t, years=args.years)
            stats["scanned"] += 1
            status = res["status"]
            if status == "insufficient_history":
                stats["skipped_no_history"] += 1
                # Don't bother queueing for deactivate — likely never had rows.
            elif status == "no_active_signal":
                stats["skipped_no_signal"] += 1
                # Still queue: deactivate scan_results AND store the
                # full analyze result.
                no_signal_chunk.append(res)
            else:  # ok
                stats["with_signals"] += 1
                chunk.append(res)
        except Exception as e:
            stats["errors"] += 1
            log.exception("scan failed for %s: %s", t, e)
        if (len(chunk) + len(no_signal_chunk)) >= args.batch:
            flush()
        if i % 100 == 0:
            log.info("  [%d/%d] %s", i, len(tickers), stats)
    flush()
    log.info("done in %.1fs: %s", time.time() - t0, stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
