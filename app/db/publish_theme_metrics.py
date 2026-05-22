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


def publish() -> int:
    """Repopulate theme_metrics_cache from theme_metrics() output.
    Returns row count written.

    Wrapped in a single transaction so /themes never sees an empty
    intermediate state — TRUNCATE then INSERT both commit atomically.
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            t0 = time.time()
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
                FROM theme_metrics()
                """
            )
            n = cur.rowcount
            dt = time.time() - t0
    log.info("theme_metrics_cache: %d rows written in %.1fs", n, dt)
    return n


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    publish()
    return 0


if __name__ == "__main__":
    sys.exit(main())
