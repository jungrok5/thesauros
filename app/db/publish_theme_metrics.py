"""Refresh `theme_metrics_cache` from the (slow) `theme_metrics()` RPC.

Background: theme_metrics() takes 9-10 s cold because it runs a window
sort over ~645k weekly bars rows. Calling it on every /themes page-load
busts Vercel's 10 s function timeout and lands users on the "테마 데이터
없음" placeholder. theme_metrics_cache (migration 046) is the snapshot
table the page reads instead. This module refreshes it.

Cadence: once a week is enough — themes themselves only refresh weekly
(see `weekly-fundamentals.yml`). Triggered from the same workflow's
end step (Saturday 02:00 UTC).

Standalone:
    python -m app.db.publish_theme_metrics

Implementation note: we first tried a SECURITY DEFINER plpgsql wrapper
in SQL, but Postgres inlined `theme_metrics()` into the INSERT statement
without honoring the outer function's `SET search_path`, so the RPC
couldn't find `theme_members`. Doing the TRUNCATE + INSERT here keeps
the schema resolution explicit and the failure mode obvious.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402

log = logging.getLogger("publish_theme_metrics")


class PublishAborted(RuntimeError):
    """RPC produced 0 rows — refuse to wipe the cache. (회고 #14)

    If we TRUNCATE-then-INSERT-0 the cache, /themes falls back to the
    slow 9-10s RPC for every user until the next weekly publish heals
    it. Better to keep the previous snapshot stale than serve 9s pages
    site-wide. Failure is loud so admin notices.
    """


# Minimum theme count we expect from a healthy theme_metrics() call.
# DB currently has 265 themes (Naver Finance). Drop to 0 means
# theme_members got wiped (e.g., the 2026-05-22 022_drop_themes replay
# incident). Below 50 we treat as unhealthy and refuse to publish.
_MIN_THEMES = 50


def publish() -> int:
    """Repopulate theme_metrics_cache from theme_metrics() output.
    Returns row count written.

    Two-phase write:
      1. SELECT count from theme_metrics() to a temp scratch.
      2. If count >= _MIN_THEMES, TRUNCATE + INSERT atomically.
      3. If count < _MIN_THEMES, raise PublishAborted — keep the
         existing (stale) cache rather than serve 9-10s RPC fallback to
         every user.

    Wrapped in a single transaction so /themes never sees an empty
    intermediate state.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            t0 = time.time()
            # Phase 1 — count probe. theme_metrics() is the slow RPC,
            # but we need its output anyway; SELECT INTO a temp avoids
            # running it twice.
            cur.execute("CREATE TEMP TABLE _tm_new AS SELECT * FROM theme_metrics()")
            cur.execute("SELECT COUNT(*) FROM _tm_new")
            new_n = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM theme_metrics_cache")
            old_n = cur.fetchone()[0]

            if new_n < _MIN_THEMES:
                log.error(
                    "theme_metrics() returned %d rows (<%d) — refusing to "
                    "TRUNCATE cache. Existing %d rows kept. Check that "
                    "themes / theme_members are populated (ingest_themes "
                    "may not have run, or 022_drop_themes replay may have "
                    "occurred).",
                    new_n, _MIN_THEMES, old_n,
                )
                raise PublishAborted(
                    f"theme_metrics() returned {new_n} rows (<{_MIN_THEMES}); "
                    f"keeping existing cache ({old_n} rows)."
                )

            # Phase 2 — atomic swap. Same transaction so partial state
            # never reaches /themes.
            cur.execute("TRUNCATE TABLE theme_metrics_cache")
            cur.execute(
                """
                INSERT INTO theme_metrics_cache (
                    theme_id, name, members, updated_at, avg_change_pct,
                    up_count, down_count, strong_buy, buy, hold, avoid,
                    top_tickers
                )
                SELECT
                    theme_id, name, members, updated_at, avg_change_pct,
                    up_count, down_count, strong_buy, buy, hold, avoid,
                    top_tickers
                FROM _tm_new
                """
            )
            n = cur.rowcount
            dt = time.time() - t0
    log.info(
        "theme_metrics_cache: %d rows written in %.1fs (prev cache had %d)",
        n, dt, old_n,
    )
    return n


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        publish()
        return 0
    except PublishAborted as e:
        # Exit non-zero so weekly-fundamentals step shows fail (with
        # continue-on-error: true the cron still proceeds), surfacing
        # the issue to the admin end-ping without wiping data.
        log.error("publish aborted: %s", e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
