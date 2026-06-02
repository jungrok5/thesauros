"""Sweep ONLY the 883 newly-ingested delisted KR tickers.

Produces data/sweep_delisted_24w.csv with the same schema as
data/sweep_all_24w.csv. We concat them in a follow-up step so the
expensive full-universe sweep (9h on 2701 tickers) is not rerun.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")
sys.path.insert(0, str(_ROOT))

from app.backtest.sweep import _parallel_walk, _save_csv  # noqa: E402
from app.db import get_conn  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("sweep_delisted")


def fetch_delisted_tickers() -> list[str]:
    with get_conn() as con:
        cur = con.cursor()
        cur.execute(
            "SELECT ticker FROM tickers "
            "WHERE is_active = false AND delisted_at IS NOT NULL "
            "AND market = ANY(ARRAY['KOSPI','KOSDAQ']) "
            "ORDER BY ticker"
        )
        return [r[0] for r in cur.fetchall()]


def main() -> int:
    tickers = fetch_delisted_tickers()
    log.info("delisted tickers to sweep: %d", len(tickers))
    hold_weeks = 24
    workers = 8
    out_path = Path("data/sweep_delisted_24w.csv")

    t0 = time.time()
    log.info("parallel mode: %d workers, hold_weeks=%d", workers, hold_weeks)
    fires = _parallel_walk(tickers, hold_weeks, workers, t0)
    log.info("sweep done: %d fires in %.1fs", len(fires), time.time() - t0)
    _save_csv(fires, out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
