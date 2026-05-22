"""Daily book-rule scan → Supabase scan_results.

For every active ticker that has at least N years of daily bars locally,
run the book analyzer and publish the *active* (recently completed) signals
to the `scan_results` table.

Strategy:
  • READ bars from Supabase (populated by ingest_bars via Naver weekly /
    monthly endpoints — yfinance is bypassed because the lib detects and
    blocks cloud-IP traffic on GH Actions).
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
from typing import Any, Dict, Iterable, List, Optional, Tuple

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
    # HOLD is normally noise. The exception is when the analyzer's
    # stretch gate downgraded a BUY/STRONG_BUY → HOLD — those rows
    # carry the "추세 유효 · 자리 지남" warning and should surface as
    # a 관망 chip on the watchlist row + stock-detail so users see why
    # ticker stopped being a buy candidate. _action_signal() guards
    # emission with the stretch_reason condition.
    "HOLD":          ("action_hold",         0.55),
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
    if not action:
        return None
    # HOLD without a stretch_reason is no-news (no chip) — same as
    # before. HOLD WITH stretch_reason means the analyzer downgraded
    # a BUY/STRONG_BUY because the chart entered late-trend stretch
    # territory; surfacing a 관망 chip with the reason lets the
    # watchlist warn the user even though no directional bet remains.
    stretch_reason = result.get("stretch_reason")
    if action == "HOLD" and not stretch_reason:
        return None
    info = SIGNAL_TYPE_MAP.get(action)
    if not info:
        return None
    stype, base_strength = info
    book_score = float(result.get("book_score") or 0)
    strength = min(1.0, max(0.0, abs(book_score) * 0.4 + base_strength * 0.6))
    reason = f"{action} (book_score={book_score:+.2f})"
    if stretch_reason:
        reason = f"{action} · {stretch_reason}"
    return {
        "signal_type": stype,
        "timeframe": "daily",
        "strength": round(strength, 3),
        "reason": reason,
        "params": {
            "book_score": book_score,
            "trend_signal": result.get("trend", {}).get("book_signal"),
            "last_close": result.get("last_close"),
            "stretch_reason": stretch_reason,
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


def _filter_movers(tickers: List[str], min_pct: float) -> List[str]:
    """Keep only tickers whose latest bar moved at least ``min_pct`` percent
    (absolute) vs the previous close. Used by --changed-pct.

    A single SQL window query computes |close - prev_close| / prev_close
    for every requested ticker's latest bar, then we filter Python-side.
    """
    if not tickers:
        return []
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH ranked AS (
                  SELECT ticker, bar_date, close,
                         LAG(close) OVER (PARTITION BY ticker ORDER BY bar_date) AS prev_close,
                         ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY bar_date DESC) AS rn
                    FROM bars
                   WHERE ticker = ANY(%s) AND granularity = 'W'
                )
                SELECT ticker, close, prev_close
                  FROM ranked
                 WHERE rn = 1
                """,
                (tickers,),
            )
            rows = cur.fetchall()
    out: List[str] = []
    for t, close, prev in rows:
        if close is None or prev in (None, 0):
            continue
        if abs(float(close) - float(prev)) / float(prev) * 100.0 >= min_pct:
            out.append(t)
    return out


def _list_tickers(markets: Optional[List[str]] = None,
                  tickers: Optional[List[str]] = None,
                  limit: Optional[int] = None) -> List[str]:
    """Pick tickers from `tickers` master table — KOSPI + KOSDAQ only
    (US universe deactivated 2026-05-22 via migration 045).

    Bars filter (2026-05-22): when callers don't pass an explicit
    ticker list, we exclude tickers that have ZERO weekly bars in DB.
    They'd fall into `skipped_no_history` anyway and waste a per-ticker
    DB lookup. EXISTS subquery is cheap because `bars` PK is
    (ticker, granularity, bar_date).

    Explicit --tickers bypass the bars filter (one-off mode used by
    analyze-ticker.yml dispatch — caller knows they want that ticker
    even if bars are empty).
    """
    where_clauses = ["is_active = true"]
    params: List[Any] = []

    if tickers:
        where_clauses.append("ticker = ANY(%s)")
        params.append(list(tickers))
    elif markets:
        where_clauses.append("market = ANY(%s)")
        params.append([m.upper() for m in markets])

    if not tickers:
        where_clauses.append(
            "EXISTS (SELECT 1 FROM bars WHERE bars.ticker = tickers.ticker "
            "AND bars.granularity = 'W')"
        )

    where = " AND ".join(where_clauses)
    sql = f"SELECT ticker, market FROM tickers WHERE {where} ORDER BY ticker"
    if limit:
        sql += f" LIMIT {int(limit)}"
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [r[0] for r in rows]


def _watchlist_tickers() -> List[str]:
    """Every ticker that at least one user has added to their watchlist.
    Lets the daily cron pick up user-chosen out-of-universe names
    (e.g. NASDAQ mid-caps not in S&P 500) on its next run."""
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT w.ticker "
                "  FROM watchlist w "
                "  JOIN tickers t ON t.ticker = w.ticker "
                " WHERE t.is_active = true"
            )
            return [r[0] for r in cur.fetchall()]


def _flush_chunk(chunk: List[Dict[str, Any]]) -> int:
    """Write a chunk of (ticker, as_of, signals) results in one transaction.

    Two SQL statements per chunk (vs. 2 per ticker in the old per-ticker
    pattern): a single bulk UPDATE deactivates all current rows for the
    chunk's tickers, then a single executemany INSERT writes the new
    signal rows.

    detected_at: ALWAYS cap to today (UTC). Otherwise weekly/monthly
    bar 's as_of (next bar close date = future) leaks into detected_at,
    which then breaks the telegram_worker dedupe (alerts.created_at >=
    signal_detected_at is always false when detected_at is in the
    future). Bug seen 2026-05-20 — same SDI alert sent 13 times.
    Tested by app/db/tests/test_scan.py::test_detected_at_never_future.
    """
    import json
    from datetime import date
    if not chunk:
        return 0
    tickers = [c["ticker"] for c in chunk]
    today = date.today()
    rows: List[Tuple[Any, ...]] = []
    for c in chunk:
        as_of = c["as_of"]
        # Cap forward-dated bar dates to today so dedupe windows work.
        if hasattr(as_of, "date"):  # datetime → date
            as_of_date = as_of.date()
        else:
            as_of_date = as_of
        if as_of_date and as_of_date > today:
            as_of_safe = today
        else:
            as_of_safe = as_of
        for s in c["signals"]:
            rows.append((
                c["ticker"], s["signal_type"], s["timeframe"],
                as_of_safe, s.get("strength", 0.5),
                s.get("reason"),
                json.dumps(s.get("params") or {}, ensure_ascii=False),
            ))
    with get_conn() as conn:
        with conn.cursor() as cur:
            # 1) Preserve detected_at for signals still active — same
            #    (ticker, signal_type, timeframe) detected previously
            #    stays at its ORIGINAL detection time (책 정신: signal
            #    의 신선도 = 최초 발견 시점). 매 scan 마다 새 detected_at
            #    stamp 하면 telegram_worker dedup 무효화 + 사용자에게
            #    같은 신호 매일 새 알림 폭주.
            #    (Bug 2026-05-21: jungrok5 에게 006400.KS enter alert 가
            #     하루 9번 발송. fix = detected_at preservation.)
            cur.execute(
                """
                SELECT ticker, signal_type, timeframe, detected_at
                  FROM scan_results
                 WHERE ticker = ANY(%s) AND is_active = true
                """,
                (tickers,),
            )
            preserved: Dict[Tuple[str, str, str], Any] = {
                (r[0], r[1], r[2]): r[3] for r in cur.fetchall()
            }
            # 2) Deactivate prior active rows (history retained via
            #    is_active=false so old detection times remain query-able).
            cur.execute(
                "UPDATE scan_results SET is_active = false "
                "WHERE ticker = ANY(%s) AND is_active = true",
                (tickers,),
            )
            # 3) Stamp with preserved detected_at when the same signal
            #    keeps firing; otherwise use the analysis bar's as_of.
            if rows:
                final_rows = [
                    (
                        r[0], r[1], r[2],
                        preserved.get((r[0], r[1], r[2]), r[3]),  # preserve or new
                        r[4], r[5], r[6],
                    )
                    for r in rows
                ]
                cur.executemany(
                    """
                    INSERT INTO scan_results
                      (ticker, signal_type, timeframe, detected_at,
                       strength, reason, params)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    final_rows,
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
    # Post-pivot input is always weekly. ~50 weekly bars = 1 year, the
    # minimum the book engine needs to compute its short MAs reliably.
    if df is None or len(df) < 50:
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


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--markets", nargs="+", default=None,
                   help="filter by market (KOSPI / KOSDAQ)")
    p.add_argument("--tickers", nargs="+", default=None,
                   help="explicit ticker list (overrides --markets)")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--years", type=int, default=5)
    p.add_argument("--batch", type=int, default=100,
                   help="flush DB rows every N tickers (default 100)")
    p.add_argument("--changed-pct", type=float, default=0.0,
                   help="incremental mode: only scan tickers whose latest |change vs prev close| ≥ this %% "
                        "(default 0 = full scan). E.g. 1.0 ≈ 'movers only'.")
    # --sp500-only removed 2026-05-22 (migration 045 deactivated US universe).
    p.add_argument("--watchlist-only", action="store_true",
                   help="Scan ONLY tickers in any user's watchlist + recently-"
                        "viewed tickers (last_accessed_at within 90d). Used "
                        "in the search-only pivot to keep alert + analyze "
                        "caches fresh for the names users actually care "
                        "about, instead of nightly-scanning the full "
                        "KR universe (~2,700) that nobody renders.")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.watchlist_only:
        # Search-only pivot: scan only what users actually care about —
        # tickers on any watchlist + recently-viewed (last_accessed_at
        # within 90d, populated by /stocks/[ticker] visits). This keeps
        # alert + analyze caches warm for the names that matter, instead
        # of scanning 2,700 KR tickers nightly for an empty audience.
        # Out-of-watchlist tickers stay handled by on-demand
        # /api/analyze/[ticker] (24h cache).
        tickers = _watchlist_tickers()
        log.info("watchlist-only mode: %d tickers", len(tickers))
    else:
        tickers = _list_tickers(markets=args.markets,
                                tickers=args.tickers,
                                limit=args.limit)

        # Always include every ticker that any user has added to their
        # watchlist (KR only post-2026-05-22 — US deactivated). Cost is
        # bounded by user count × ~10 picks. Only applies when scanning
        # a market filter (not explicit --tickers).
        if not args.tickers:
            wl = _watchlist_tickers()
            if wl:
                before = len(tickers)
                tickers = sorted(set(tickers) | set(wl))
                added = len(tickers) - before
                if added > 0:
                    log.info("+%d tickers from user watchlists", added)

    if args.changed_pct > 0:
        before = len(tickers)
        tickers = _filter_movers(tickers, args.changed_pct)
        log.info("changed-pct=%.2f: %d → %d movers", args.changed_pct, before, len(tickers))

    log.info("scanning %d tickers (years=%d, batch=%d)",
             len(tickers), args.years, args.batch)
    t0 = time.time()
    stats = {"scanned": 0, "with_signals": 0, "inserted": 0,
             "analyze_upserted": 0,
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
