"""DB retention enforcement — keep Supabase under the 500MB free tier.

Each cron-fed ingest module calls the matching `prune_*` function as its
last step. Idempotent — re-running on already-pruned data is a no-op.

All timestamps in the DB are stored as UTC (Postgres `TIMESTAMPTZ`).
The `CURRENT_DATE - INTERVAL 'N days'` boundaries below evaluate in the
session's timezone — make sure the GitHub Actions runner is UTC (default
on `ubuntu-latest`).

Retention windows chosen so the site's display + analysis still has the
data it needs:

  bars (W)        5 years  (≈260 weekly rows per ticker; book MAs go up to 240)
  bars (M)        5 years  (≈60 monthly rows per ticker)
  investor_flow   14 days  (site shows last 5; 14 buffers any drill-down)
  disclosures     180 days + engagement set
  fundamentals    engagement set only (5 years rolling per ticker)
  scan_results    inactive ≥ 14 days  (active signals stay; cron toggles flags)

`macro_series`, `tickers`, `analyze_results`, `financials_eval`,
`factors_eval` are either bounded by universe size or already
overwritten in place; no retention needed.

**Engagement set** = KR universe (KOSPI + KOSDAQ active) ∪ watchlisted
tickers (category='holding' OR last_accessed_at within 90 days). Anything
outside is "data we no longer need" — applies symmetrically to bars,
fundamentals, disclosures, scan_results, analyze_results. The watchlist
row itself is never touched; if the user re-visits, the next cron
re-ingests.

Note (2026-05-19): theme_daily / themes / theme_members were dropped
along with the /themes page in the search-only pivot.

Run standalone:
    python -m app.db.retention            # prune all
    python -m app.db.retention --dry-run  # show counts, no DELETE
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Callable, Tuple, Union

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402

log = logging.getLogger("retention")


def _prune_e2e_users(dry_run: bool) -> int:
    """Clean up @e2e.test artifacts older than 1 day. Needs two SQL
    statements because access_requests.decided_by is ON DELETE RESTRICT
    so we NULL it for any test-admin decisions before the user delete.
    """
    select_stale = (
        "SELECT id FROM users "
        "WHERE email ILIKE '%@e2e.test' "
        "AND created_at < CURRENT_DATE - INTERVAL '1 day'"
    )
    if dry_run:
        with get_conn(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM ({select_stale}) s")
                return cur.fetchone()[0]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE access_requests SET decided_by = NULL "
                f"WHERE decided_by IN ({select_stale})"
            )
            cur.execute(
                "DELETE FROM users WHERE email ILIKE '%@e2e.test' "
                "AND created_at < CURRENT_DATE - INTERVAL '1 day'"
            )
            return cur.rowcount


# (table, sql_or_callable, description). String → single-statement DELETE
# with auto dry-run conversion. Callable → custom (e.g. multi-statement
# users cleanup with FK NULL-out first).
Policy = Tuple[str, Union[str, Callable[[bool], int]], str]

POLICIES: list[Policy] = [
    (
        "bars",
        "DELETE FROM bars WHERE bar_date < CURRENT_DATE - INTERVAL '5 years'",
        "5 years (W + M) — 240MA 4.6y; backfill 효과 미미해 6년 rollback",
    ),
    (
        "investor_flow",
        "DELETE FROM investor_flow WHERE day < CURRENT_DATE - INTERVAL '14 days'",
        "14 days",
    ),
    (
        "disclosures",
        "DELETE FROM disclosures WHERE filed_date < CURRENT_DATE - INTERVAL '180 days'",
        "180 days",
    ),
    (
        "scan_results",
        "DELETE FROM scan_results "
        "WHERE is_active = false "
        "AND detected_at < CURRENT_DATE - INTERVAL '5 days'",
        # Tightened 14→5d on 2026-05-27 — Daily Data Refresh failed
        # with DB at 94% of 500MB cap. 14d cutoff only caught ~2k
        # inactive rows/cron while ~70k inactive rows in the 5-14d
        # window sat as dead weight (signals that fired but turned
        # off within a week). 5d still covers "지난 한 주 신호" UX
        # and shrank the table from 56MB → ~22MB.
        # 14d→5d change: emergency cleanup deleted 71k rows + freed
        # 35MB via VACUUM FULL scan_results.
        "inactive ≥ 5 days",
    ),
    # theme_daily retention removed 2026-05-19 — tables dropped along
    # with /themes page in the search-only pivot.
    # Alerts pile up at ~1-3 rows per user per signal-bearing ticker per
    # day. 60 days of history is plenty for "did I get notified about
    # this?" — older rows are dead weight. Tightened from 90 to 60 days
    # (2026-05-20) to keep DB under 90% of Supabase 500MB cap.
    (
        "alerts",
        "DELETE FROM alerts WHERE created_at < CURRENT_DATE - INTERVAL '60 days'",
        "60 days",
    ),
    # ──────────────────────────────────────────────────────────────────
    # Generated-data TTL via engagement. The `active set` is the union
    # of the default scan universe (KOSPI/KOSDAQ — always kept) and any
    # ticker that has a FRESH watchlist entry (last_accessed_at within
    # 90 days; `holding` category never goes stale because the user has
    # money in it). Anything outside that set has its generated data
    # purged. The watchlist row itself is NEVER touched — the user
    # owns it. If they view the ticker again, last_accessed_at refreshes
    # and the next cron regenerates the data via Naver / FDR / SEC.
    # ──────────────────────────────────────────────────────────────────
    (
        "bars",
        """
        DELETE FROM bars WHERE ticker NOT IN (
            SELECT ticker FROM tickers
             WHERE is_active = true AND market IN ('KOSPI','KOSDAQ')
            UNION
            SELECT DISTINCT ticker FROM watchlist
             WHERE category = 'holding'
                OR last_accessed_at >= CURRENT_DATE - INTERVAL '90 days'
        )
        """,
        "outside KR universe ∪ engaged watchlist",
    ),
    (
        "scan_results",
        """
        DELETE FROM scan_results WHERE ticker NOT IN (
            SELECT ticker FROM tickers
             WHERE is_active = true AND market IN ('KOSPI','KOSDAQ')
            UNION
            SELECT DISTINCT ticker FROM watchlist
             WHERE category = 'holding'
                OR last_accessed_at >= CURRENT_DATE - INTERVAL '90 days'
        )
        """,
        "same engagement set",
    ),
    (
        "analyze_results",
        """
        DELETE FROM analyze_results WHERE ticker NOT IN (
            SELECT ticker FROM tickers
             WHERE is_active = true AND market IN ('KOSPI','KOSDAQ')
            UNION
            SELECT DISTINCT ticker FROM watchlist
             WHERE category = 'holding'
                OR last_accessed_at >= CURRENT_DATE - INTERVAL '90 days'
        )
        """,
        "same engagement set",
    ),
    # `fundamentals` is per-(ticker, concept, fy). DART writes KR (already
    # covered by the KOSPI/KOSDAQ universe arm); SEC writes US which can
    # be unbounded if every searched US ticker keeps accumulating. Same
    # engagement filter as bars — non-KR ticker must be watchlisted (or
    # recently accessed) to keep its fundamentals.
    (
        "fundamentals",
        """
        DELETE FROM fundamentals WHERE ticker NOT IN (
            SELECT ticker FROM tickers
             WHERE is_active = true AND market IN ('KOSPI','KOSDAQ')
            UNION
            SELECT DISTINCT ticker FROM watchlist
             WHERE category = 'holding'
                OR last_accessed_at >= CURRENT_DATE - INTERVAL '90 days'
        )
        """,
        "outside engagement set",
    ),
    # `disclosures` already has the 1-year date filter above; this adds
    # the engagement filter so a US ticker that was searched once a year
    # ago doesn't keep its 30 SEC filings forever just because the
    # date-based rule treats them as "fresh".
    (
        "disclosures",
        """
        DELETE FROM disclosures WHERE ticker NOT IN (
            SELECT ticker FROM tickers
             WHERE is_active = true AND market IN ('KOSPI','KOSDAQ')
            UNION
            SELECT DISTINCT ticker FROM watchlist
             WHERE category = 'holding'
                OR last_accessed_at >= CURRENT_DATE - INTERVAL '90 days'
        )
        """,
        "outside engagement set",
    ),
    # Feedback tickets: keep open + in-progress forever; closed ones
    # (resolved or wont-fix) are dead weight after 90 days. updated_at
    # is bumped by the touch_feedback_updated_at trigger on status
    # changes, so this counts from when the ticket actually closed.
    (
        "feedback",
        """
        DELETE FROM feedback
         WHERE status IN ('resolved', 'wont_fix')
           AND updated_at < CURRENT_DATE - INTERVAL '90 days'
        """,
        "closed ≥ 90 days",
    ),
    # Disclosure-alert dedupe: only purpose is "don't alert the same
    # rcept_no twice". After 14 days, the disclosure is past — even
    # if we forget we'd already alerted, the disclosure's filed_date
    # window (days_back=2) wouldn't include it again. 14d buffer.
    (
        "disclosure_alert_seen",
        "DELETE FROM disclosure_alert_seen WHERE sent_at < CURRENT_DATE - INTERVAL '14 days'",
        "14 days",
    ),
    # Short-sales history: daily rows × ~2700 KR tickers grow ~700K/year.
    # 90 days is enough for trend cards + matches scan_results retention.
    (
        "short_sales",
        "DELETE FROM short_sales WHERE day < CURRENT_DATE - INTERVAL '90 days'",
        "90 days",
    ),
    # Short-sales engagement filter — match bars/fundamentals so a
    # one-time-searched ticker doesn't keep accumulating daily rows.
    (
        "short_sales",
        """
        DELETE FROM short_sales WHERE ticker NOT IN (
            SELECT ticker FROM tickers
             WHERE is_active = true AND market IN ('KOSPI','KOSDAQ')
            UNION
            SELECT DISTINCT ticker FROM watchlist
             WHERE category = 'holding'
                OR last_accessed_at >= CURRENT_DATE - INTERVAL '90 days'
        )
        """,
        "outside engagement set",
    ),
    # market_warnings + dividend_info don't accumulate per-day — single
    # row per (ticker, level) / (ticker) respectively. Stale rows are
    # overwritten in place by the next ingest. Just sweep tickers
    # outside the engagement set.
    (
        "market_warnings",
        """
        DELETE FROM market_warnings WHERE ticker NOT IN (
            SELECT ticker FROM tickers
             WHERE is_active = true AND market IN ('KOSPI','KOSDAQ')
            UNION
            SELECT DISTINCT ticker FROM watchlist
             WHERE category = 'holding'
                OR last_accessed_at >= CURRENT_DATE - INTERVAL '90 days'
        )
        """,
        "outside engagement set",
    ),
    (
        "dividend_info",
        """
        DELETE FROM dividend_info WHERE ticker NOT IN (
            SELECT ticker FROM tickers
             WHERE is_active = true AND market IN ('KOSPI','KOSDAQ')
            UNION
            SELECT DISTINCT ticker FROM watchlist
             WHERE category = 'holding'
                OR last_accessed_at >= CURRENT_DATE - INTERVAL '90 days'
        )
        """,
        "outside engagement set",
    ),
    # macro_series — FRED + BOK 등 47 지표 × 시계열.
    # dashboard 카드가 최근 값 + YoY 만 사용 → 13개월 윈도우면 충분.
    # 5+ 년 시계열은 dead. 2026-05-20 retention 추가.
    (
        "macro_series",
        "DELETE FROM macro_series WHERE date < CURRENT_DATE - INTERVAL '13 months'",
        "13 months — YoY 계산 + buffer",
    ),
    # fundamentals — DART/SEC 재무. financials_eval 이 최근 3년치만 사용.
    # 5년 fy 보유 = 3년 분석 + 2년 비교 buffer. 그 이상은 dead.
    # 2026-05-20 retention 추가 — 이전엔 누적만 됐음.
    (
        "fundamentals",
        "DELETE FROM fundamentals WHERE fy < EXTRACT(YEAR FROM CURRENT_DATE)::int - 5",
        "5 fiscal years — financials_eval 3y + buffer",
    ),
    # ──────────────────────────────────────────────────────────────────
    # Investor-intel (migration 029): earnings_calendar / analyst_consensus
    # / institutional_ownership. All three are per-ticker, so they also
    # need the engagement filter so a one-time US search doesn't keep
    # eating rows.
    # ──────────────────────────────────────────────────────────────────
    # earnings_calendar: past dates 90 days back can be pruned (actual
    # already merged in; users don't browse "what was reported last
    # year"). Future-dated rows are the live signal — keep until they
    # become past.
    (
        "earnings_calendar",
        "DELETE FROM earnings_calendar "
        "WHERE expected_date < CURRENT_DATE - INTERVAL '90 days'",
        "past expected_date > 90 days",
    ),
    (
        "earnings_calendar",
        """
        DELETE FROM earnings_calendar WHERE ticker NOT IN (
            SELECT ticker FROM tickers
             WHERE is_active = true AND market IN ('KOSPI','KOSDAQ')
            UNION
            SELECT DISTINCT ticker FROM watchlist
             WHERE category = 'holding'
                OR last_accessed_at >= CURRENT_DATE - INTERVAL '90 days'
        )
        """,
        "outside engagement set",
    ),
    # analyst_consensus: keep last 3 fiscal years (current + 2). Older
    # fiscal years are noise — the consensus is for forecasting.
    (
        "analyst_consensus",
        "DELETE FROM analyst_consensus "
        "WHERE fiscal_year < EXTRACT(YEAR FROM CURRENT_DATE)::int - 2",
        "fiscal_year < current - 2",
    ),
    (
        "analyst_consensus",
        """
        DELETE FROM analyst_consensus WHERE ticker NOT IN (
            SELECT ticker FROM tickers
             WHERE is_active = true AND market IN ('KOSPI','KOSDAQ')
            UNION
            SELECT DISTINCT ticker FROM watchlist
             WHERE category = 'holding'
                OR last_accessed_at >= CURRENT_DATE - INTERVAL '90 days'
        )
        """,
        "outside engagement set",
    ),
    # institutional_ownership: 5% reports are filed sporadically. Keep
    # 2 years of history so the user can see "이 펀드 작년에 들어왔다"
    # type narratives, but older filings are noise.
    (
        "institutional_ownership",
        "DELETE FROM institutional_ownership "
        "WHERE reported_date < CURRENT_DATE - INTERVAL '2 years'",
        "2 years",
    ),
    (
        "institutional_ownership",
        """
        DELETE FROM institutional_ownership WHERE ticker NOT IN (
            SELECT ticker FROM tickers
             WHERE is_active = true AND market IN ('KOSPI','KOSDAQ')
            UNION
            SELECT DISTINCT ticker FROM watchlist
             WHERE category = 'holding'
                OR last_accessed_at >= CURRENT_DATE - INTERVAL '90 days'
        )
        """,
        "outside engagement set",
    ),
    # search_history is self-trimming via the trg_trim_search_history
    # trigger (30 newest per user). No retention rule needed.
    # investor_flow is KR-only by construction (Naver frgn page), so
    # the date-based 90d rule above already handles it.
    # E2E test artifacts — Playwright sessions upsert @e2e.test users
    # via /api/e2e-test/issue-session. The session-mint endpoint does
    # its own rolling 1h GC; this is the daily safety net for any
    # stragglers. access_requests.decided_by is ON DELETE RESTRICT so
    # the callable above NULLs test-admin decisions first, then deletes.
    ("users", _prune_e2e_users, "e2e test users 24h"),
]


def prune_one(
    table: str,
    sql_or_fn: Union[str, Callable[[bool], int]],
    dry_run: bool = False,
) -> int:
    """Run a single retention rule; return rows affected. Strings are
    auto-converted DELETE→COUNT for dry runs; callables get a dry_run flag."""
    if callable(sql_or_fn):
        return sql_or_fn(dry_run)
    sql = sql_or_fn
    if dry_run:
        count_sql = sql.replace("DELETE FROM", "SELECT COUNT(*) FROM", 1)
        with get_conn(autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(count_sql)
                return cur.fetchone()[0]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.rowcount


# Per-table convenience wrappers — each ingest module imports its own.

def prune_bars() -> int:
    return prune_one(*POLICIES[0][:2])


def prune_investor_flow() -> int:
    return prune_one(*POLICIES[1][:2])


def prune_disclosures() -> int:
    return prune_one(*POLICIES[2][:2])


def prune_scan_results() -> int:
    return prune_one(*POLICIES[3][:2])


# Postgres advisory-lock key — unique 32-bit int. 사용처는 retention.py
# 만이라 충돌 없음 (회고 #19/#56 — daily-data + weekly-scan 동시 발사 시
# retention 이 중복 실행되는 race 방지).
_RETENTION_LOCK_KEY = 0xC1A5_5C0D   # 임의로 고른 magic number


def _try_advisory_lock() -> bool:
    """Try pg_try_advisory_lock(key) — return True if acquired, False
    if another session already holds it. Lock auto-releases on session
    end. Cross-cron protection only (single session within a script is
    OK to reuse)."""
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (_RETENTION_LOCK_KEY,))
            got = cur.fetchone()[0]
    return bool(got)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-lock", action="store_true",
                   help="advisory lock 건너뛰기 (테스트/긴급 용)")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    )

    # Advisory lock — daily-data 와 weekly-scan 이 같은 시각에 retention
    # 둘 다 호출하면 DELETE 충돌 + dead tuple 폭증 가능. 두 번째 호출은
    # skip + 종료 (0). admin notification 은 cron 의 end-ping 이 처리.
    if not args.no_lock:
        if not _try_advisory_lock():
            log.info(
                "retention skipped — another session holds the lock "
                "(another cron concurrent). graceful exit."
            )
            return 0

    verb = "would delete" if args.dry_run else "deleted"
    total = 0
    touched: set[str] = set()
    for table, sql, desc in POLICIES:
        n = prune_one(table, sql, dry_run=args.dry_run)
        total += n
        if n > 0:
            touched.add(table)
        log.info("%-15s (retain %s)  %s %d rows", table, desc, verb, n)
    log.info("total: %s %d rows", verb, total)

    # 2026-05-28 — also VACUUM ANALYZE the heavy-write tables that the
    # retention loop didn't necessarily DELETE from this run. Without
    # this, autovacuum on alerts (insert-mostly) + analyze_results
    # (UPSERT of ~2700 large JSONB rows per scan_daily) waits for the
    # 20% dead-tuple threshold, leaving statistics stale → query
    # planner picks bad join orders for screener_results et al.
    _ALWAYS_VACUUM = {"alerts", "analyze_results", "factors_eval"}
    touched = touched | _ALWAYS_VACUUM

    # VACUUM (non-FULL) on tables that lost rows so dead tuples are
    # marked reusable. Doesn't shrink the table on disk (that needs
    # VACUUM FULL which locks the table — bad for a live site), but
    # keeps further inserts from growing the heap. Autovacuum normally
    # handles this but defaults are conservative (20% dead tuples), so
    # we nudge it whenever we just did a big delete.
    if not args.dry_run and touched:
        with get_conn(autocommit=True) as conn:
            with conn.cursor() as cur:
                for tbl in sorted(touched):
                    try:
                        cur.execute(f"VACUUM ANALYZE {tbl}")
                        log.info("VACUUM ANALYZE %s done", tbl)
                    except Exception as e:
                        log.warning("VACUUM %s failed: %s", tbl, e)

    # DB size gate — Supabase free tier hard cap = 500MB. We can't
    # silently approach that line because Supabase puts the DB in
    # read-only mode mid-cron when it trips, leaving inconsistent
    # state. After retention we measure + escalate:
    #   < 85%  → quiet (normal headroom)
    #   85-90% → WARN log (telegram-able)
    #   90%+   → ERR log + run VACUUM FULL bars (biggest table) to
    #            reclaim bloat. If that still doesn't bring it under
    #            90%, exit non-zero so the cron step fails and we get
    #            a GitHub Actions notification.
    SOFT_LIMIT = 0.85
    HARD_LIMIT = 0.90
    SUPABASE_FREE_BYTES = 500_000_000
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_database_size(current_database())")
            size = cur.fetchone()[0]
    pct = size / SUPABASE_FREE_BYTES
    log.info("DB size: %s (%.1f%% of 500MB cap)",
             _human(size), pct * 100)
    if pct < SOFT_LIMIT:
        return 0
    if pct < HARD_LIMIT:
        log.warning("DB size %.1f%% — approaching Supabase free cap, "
                    "consider tightening retention windows", pct * 100)
        return 0

    # HARD_LIMIT crossed — run VACUUM FULL on bars (biggest table) to
    # reclaim disk. VACUUM FULL locks the table for the duration but
    # bars writes only happen during the cron itself (we're at the
    # retention step which runs LAST), so the lock is safe here.
    log.error("DB size %.1f%% — running emergency VACUUM FULL bars", pct * 100)
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("VACUUM FULL bars")
            log.info("VACUUM FULL bars done")
            cur.execute("SELECT pg_database_size(current_database())")
            size_after = cur.fetchone()[0]
    pct_after = size_after / SUPABASE_FREE_BYTES
    log.info("DB size after VACUUM FULL: %s (%.1f%%)",
             _human(size_after), pct_after * 100)
    if pct_after >= HARD_LIMIT:
        log.error("STILL above %d%% after VACUUM FULL — exiting "
                  "non-zero so cron fails and admin is notified",
                  int(HARD_LIMIT * 100))
        return 2
    return 0


def _human(b: int) -> str:
    """Bytes → '123 MB' style. Matches pg_size_pretty enough for logs."""
    if b >= 1 << 30:
        return f"{b / (1 << 30):.1f} GB"
    if b >= 1 << 20:
        return f"{b / (1 << 20):.0f} MB"
    if b >= 1 << 10:
        return f"{b / (1 << 10):.0f} KB"
    return f"{b} B"


if __name__ == "__main__":
    sys.exit(main())
