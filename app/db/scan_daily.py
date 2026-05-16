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


def _deactivate_old(conn, ticker: str, signal_types: Iterable[str]) -> None:
    """Mark ALL previous active rows for this ticker as inactive.

    Rationale: each scan reproduces the full active-signal set for the
    ticker at that moment. Any signal that has disappeared (e.g. pattern
    completed last week but no longer "live") must be deactivated even if
    it wasn't in this scan's new signal types. Historical rows stay in
    table (is_active=false) for analytics.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE scan_results SET is_active = false "
            "WHERE ticker = %s AND is_active = true",
            (ticker,),
        )


def _insert_signals(conn, ticker: str, as_of: pd.Timestamp,
                    signals: List[Dict[str, Any]]) -> int:
    import json
    if not signals:
        return 0
    rows = []
    for s in signals:
        rows.append((
            ticker, s["signal_type"], s["timeframe"],
            as_of, s.get("strength", 0.5),
            s.get("reason"),
            json.dumps(s.get("params") or {}, ensure_ascii=False),
        ))
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO scan_results
              (ticker, signal_type, timeframe, detected_at, strength, reason, params)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            rows,
        )
    return len(rows)


def scan_one(ticker: str, years: int = 5) -> Dict[str, Any]:
    df = load_ticker_data(ticker, years=years)
    if df is None or len(df) < 250:
        return {"ticker": ticker, "skipped": "insufficient_history",
                "rows": 0 if df is None else len(df)}
    result = analyze_ticker(ticker, df)
    signals = extract_signals(result)
    if not signals:
        return {"ticker": ticker, "skipped": "no_active_signal", "rows": len(df)}
    types = [s["signal_type"] for s in signals]
    as_of = pd.Timestamp(result.get("as_of"))
    with get_conn() as conn:
        _deactivate_old(conn, ticker, types)
        n = _insert_signals(conn, ticker, as_of, signals)
    return {"ticker": ticker, "inserted": n, "signals": [s["signal_type"] for s in signals]}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--markets", nargs="+", default=None,
                   help="filter by market (KOSPI / KOSDAQ / NASDAQ)")
    p.add_argument("--tickers", nargs="+", default=None,
                   help="explicit ticker list (overrides --markets)")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--years", type=int, default=5)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    tickers = _list_tickers(markets=args.markets,
                            tickers=args.tickers,
                            limit=args.limit)
    log.info("scanning %d tickers (years=%d)", len(tickers), args.years)
    t0 = time.time()
    stats = {"scanned": 0, "with_signals": 0, "inserted": 0,
             "skipped_no_history": 0, "skipped_no_signal": 0, "errors": 0}
    for i, t in enumerate(tickers, 1):
        try:
            res = scan_one(t, years=args.years)
            stats["scanned"] += 1
            if res.get("skipped") == "insufficient_history":
                stats["skipped_no_history"] += 1
            elif res.get("skipped") == "no_active_signal":
                stats["skipped_no_signal"] += 1
            elif res.get("inserted"):
                stats["with_signals"] += 1
                stats["inserted"] += res["inserted"]
        except Exception as e:
            stats["errors"] += 1
            log.exception("scan failed for %s: %s", t, e)
        if i % 50 == 0:
            log.info("  [%d/%d] %s", i, len(tickers), stats)
    log.info("done in %.1fs: %s", time.time() - t0, stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
