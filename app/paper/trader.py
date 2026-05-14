"""Paper-trading recorder + evaluator.

Single source of truth is the `paper_trades` table (created in pit_db.py):

  snapshot_date   DATE      — when system recommended the trade
  ticker          VARCHAR
  action          VARCHAR   — STRONG_BUY / BUY / SELL …
  book_score      DOUBLE
  entry_price     DOUBLE    — close price on snapshot_date (proxy for fill)
  stop_price      DOUBLE
  target_price    DOUBLE
  based_on        VARCHAR   — pattern that drove the entry plan
  source          VARCHAR   — 'book_rules' / 'ml_v3' / etc.

  closed          BOOLEAN
  close_date      DATE
  close_price     DOUBLE
  close_reason    VARCHAR   — TARGET / STOP / TIMEOUT / OPEN
  realized_pct    DOUBLE

Source is part of the PK so the same ticker can be recommended by both
the book engine and the ML engine on the same day, tracked separately.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional

import pandas as pd

from app.data.pit_db import connect, cursor


DEFAULT_MAX_HOLD_DAYS = 90        # close any open trade after 90 trading days
DEFAULT_SOURCE = "book_rules"


# ---------------------------------------------------------------------------
# Record a daily snapshot
# ---------------------------------------------------------------------------
def record_snapshot(items: List[Dict],
                    snapshot_date: Optional[date] = None,
                    source: str = DEFAULT_SOURCE,
                    verbose: bool = True) -> int:
    """Persist a list of recommendations as paper trades.

    `items` should match the shape of /api/book/screen .items[*]:
      { ticker, action, book_score, last_close, entry_plan: {entry, stop, target, based_on} }

    Returns: number of new rows inserted (existing PK collisions are ignored).
    """
    if not items:
        return 0
    snapshot_date = snapshot_date or date.today()

    rows = []
    for it in items:
        ep = (it.get("entry_plan") or {})
        rows.append({
            "snapshot_date": snapshot_date,
            "ticker": it["ticker"],
            "action": it.get("action", "HOLD"),
            "book_score": float(it.get("book_score") or 0.0),
            "entry_price": float(ep.get("entry") or it.get("last_close") or 0.0),
            "stop_price": float(ep.get("stop") or 0.0),
            "target_price": float(ep.get("target") or 0.0),
            "based_on": ep.get("based_on") or "",
            "source": source,
            "closed": False,
            "close_date": None,
            "close_price": None,
            "close_reason": "OPEN",
            "realized_pct": None,
        })

    df = pd.DataFrame(rows)
    con = connect()
    try:
        con.register("df_in", df)
        # INSERT OR IGNORE because if we run twice on the same day, we keep
        # the first snapshot (don't overwrite an opened trade).
        con.execute("""
            INSERT OR IGNORE INTO paper_trades
              (snapshot_date, ticker, action, book_score, entry_price,
               stop_price, target_price, based_on, source,
               closed, close_date, close_price, close_reason, realized_pct)
            SELECT snapshot_date, ticker, action, book_score, entry_price,
                   stop_price, target_price, based_on, source,
                   closed, close_date, close_price, close_reason, realized_pct
            FROM df_in
        """)
        n = con.execute(
            "SELECT COUNT(*) FROM paper_trades WHERE snapshot_date = ?"
            " AND source = ?",
            [snapshot_date, source],
        ).fetchone()[0]
    finally:
        con.close()
    if verbose:
        print(f"[paper] snapshot {snapshot_date}: {len(rows)} items, "
              f"DB rows for date={n}")
    return len(rows)


# ---------------------------------------------------------------------------
# Evaluate open trades against current prices
# ---------------------------------------------------------------------------
def evaluate_open_trades(as_of: Optional[date] = None,
                        max_hold_days: int = DEFAULT_MAX_HOLD_DAYS,
                        verbose: bool = True) -> Dict:
    """Iterate every OPEN trade and check stop/target/timeout."""
    as_of = as_of or date.today()
    with cursor() as con:
        open_rows = con.execute(
            "SELECT * FROM paper_trades WHERE closed = FALSE"
        ).df()

    if open_rows.empty:
        if verbose:
            print("[paper] no open trades.")
        return {"closed": 0, "open": 0}

    # Pull all needed prices at once.
    tickers = open_rows["ticker"].unique().tolist()
    with cursor() as con:
        px = con.execute(
            "SELECT ticker, date, high, low, close FROM prices WHERE ticker = ANY(?)",
            [tickers],
        ).df()
    px["date"] = pd.to_datetime(px["date"])

    n_closed = 0
    rows_to_update = []
    for _, t in open_rows.iterrows():
        snap = pd.Timestamp(t["snapshot_date"])
        cutoff = pd.Timestamp(as_of)
        tk_px = px[(px["ticker"] == t["ticker"])
                   & (px["date"] > snap)
                   & (px["date"] <= cutoff)].sort_values("date")
        if tk_px.empty:
            continue

        close_date = None
        close_price = None
        reason = None
        stop = float(t["stop_price"] or 0)
        target = float(t["target_price"] or 0)

        for _, bar in tk_px.iterrows():
            hit_stop = stop > 0 and bar["low"] <= stop
            hit_target = target > 0 and bar["high"] >= target
            # If both hit on same bar, assume STOP (worst case).
            if hit_stop and not hit_target:
                close_date = bar["date"].date()
                close_price = stop
                reason = "STOP"
                break
            if hit_target and not hit_stop:
                close_date = bar["date"].date()
                close_price = target
                reason = "TARGET"
                break
            if hit_stop and hit_target:
                close_date = bar["date"].date()
                close_price = stop
                reason = "STOP_PRIORITIZED"
                break

        # Timeout check
        if close_date is None:
            held = (cutoff - snap).days
            if held >= max_hold_days:
                last_bar = tk_px.iloc[-1]
                close_date = last_bar["date"].date()
                close_price = float(last_bar["close"])
                reason = "TIMEOUT"

        if close_date is not None:
            entry = float(t["entry_price"])
            realized = ((close_price - entry) / entry * 100.0) if entry > 0 else 0.0
            rows_to_update.append({
                "snapshot_date": t["snapshot_date"],
                "ticker": t["ticker"],
                "source": t["source"],
                "close_date": close_date,
                "close_price": close_price,
                "close_reason": reason,
                "realized_pct": realized,
            })

    if rows_to_update:
        upd = pd.DataFrame(rows_to_update)
        con = connect()
        try:
            con.register("df_upd", upd)
            con.execute("""
                UPDATE paper_trades
                SET closed = TRUE,
                    close_date = df_upd.close_date,
                    close_price = df_upd.close_price,
                    close_reason = df_upd.close_reason,
                    realized_pct = df_upd.realized_pct
                FROM df_upd
                WHERE paper_trades.snapshot_date = df_upd.snapshot_date
                  AND paper_trades.ticker = df_upd.ticker
                  AND paper_trades.source = df_upd.source
            """)
            n_closed = len(rows_to_update)
        finally:
            con.close()

    with cursor() as con:
        still_open = con.execute(
            "SELECT COUNT(*) FROM paper_trades WHERE closed = FALSE"
        ).fetchone()[0]

    if verbose:
        print(f"[paper] closed {n_closed} trade(s); {still_open} still open.")
    return {"closed": n_closed, "open": still_open}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def paper_metrics(source: Optional[str] = None) -> Dict:
    """Aggregate paper-trading performance.

    Returns dict with overall + by-pattern + by-action breakdowns.
    """
    where = ""
    args: List = []
    if source:
        where = "WHERE source = ?"
        args.append(source)

    with cursor() as con:
        all_df = con.execute(
            f"SELECT * FROM paper_trades {where}", args
        ).df()
        closed_df = con.execute(
            f"SELECT * FROM paper_trades WHERE closed = TRUE "
            f"{('AND ' + where[6:]) if where else ''}",
            args,
        ).df()

    n_total = len(all_df)
    n_open = int((all_df["closed"] == False).sum()) if not all_df.empty else 0
    n_closed = len(closed_df)

    if closed_df.empty:
        return {"n_total": n_total, "n_open": n_open, "n_closed": 0}

    win_rate = float((closed_df["realized_pct"] > 0).mean() * 100)
    avg = float(closed_df["realized_pct"].mean())
    avg_win = float(closed_df.loc[closed_df["realized_pct"] > 0,
                                  "realized_pct"].mean() or 0.0)
    avg_loss = float(closed_df.loc[closed_df["realized_pct"] <= 0,
                                   "realized_pct"].mean() or 0.0)
    by_reason = closed_df.groupby("close_reason")["realized_pct"].agg(
        ["count", "mean"]
    ).reset_index().to_dict("records")
    by_pattern = closed_df.groupby("based_on")["realized_pct"].agg(
        ["count", "mean"]
    ).reset_index().to_dict("records")

    return {
        "n_total": n_total,
        "n_open": n_open,
        "n_closed": n_closed,
        "win_rate_pct": win_rate,
        "avg_return_pct": avg,
        "avg_winner_pct": avg_win,
        "avg_loser_pct": avg_loss,
        "by_reason": by_reason,
        "by_pattern": by_pattern,
    }
