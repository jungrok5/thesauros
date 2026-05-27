"""Phase 2 grid search — fix weight (V2 = 80% book / 20% q) and vary
the q definition itself.

Phase 1 (grid_search_quality.py) found 20% quality weight produces
the best risk-adjusted result (Calmar 0.44, DD 41.6%) when q is
defined as (quality_score + safety_score) / 20. Phase 2 asks: with
that weight, which q DEFINITION makes the most book-spirit-honest
ranking?

5 variants of q:
  Q0: quality + safety  (Phase 1's baseline — V2)
  Q1: quality only      — ROE + ROA + op_margin (사업 quality 단일)
  Q2: safety only       — debt low (재무 안전 단일)
  Q3: Buffett gate      — passes_buffett boolean (1 or 0)
  Q4: All factors mean  — (quality + safety + growth + value) / 4

Same 80% book / 20% q weighting throughout. Same fires CSV.
"""
from __future__ import annotations

import csv
import sys
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.backtest import portfolio as P
from app.backtest.metrics import compute_full_metrics
from app.db.connection import get_conn

BOOK_WEIGHT = 0.8
QUALITY_WEIGHT = 0.2


def load_q_map(definition: str) -> dict:
    """Returns {ticker: q_value in [0, 1]} for the given definition."""
    out: dict[str, float] = {}
    sql_by_def = {
        "Q0_quality_safety":
            "SELECT ticker, "
            "       (COALESCE(quality_score,0) + COALESCE(safety_score,0)) / 20.0 "
            "FROM factors_eval "
            "WHERE quality_score IS NOT NULL AND safety_score IS NOT NULL",
        "Q1_quality_only":
            "SELECT ticker, COALESCE(quality_score,0) / 10.0 FROM factors_eval "
            "WHERE quality_score IS NOT NULL",
        "Q2_safety_only":
            "SELECT ticker, COALESCE(safety_score,0) / 10.0 FROM factors_eval "
            "WHERE safety_score IS NOT NULL",
        "Q3_buffett_gate":
            "SELECT ticker, CASE WHEN passes_buffett THEN 1.0 ELSE 0.0 END "
            "FROM factors_eval",
        "Q4_all_factors":
            "SELECT ticker, "
            "       (COALESCE(quality_score,0) + COALESCE(safety_score,0) + "
            "        COALESCE(growth_score,0) + COALESCE(value_score,0)) / 40.0 "
            "FROM factors_eval",
    }
    sql = sql_by_def[definition]
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql)
        for ticker, val in cur.fetchall():
            out[ticker] = float(val) if val is not None else 0.0
    return out


def reranked(fires, q_map, max_strength):
    out = []
    for f in fires:
        s = float(f.get("strength", 0))
        s_n = s / max_strength if max_strength > 0 else 0
        q = q_map.get(f["ticker"], 0)
        score = BOOK_WEIGHT * s_n + QUALITY_WEIGHT * q
        new_f = dict(f)
        new_f["strength"] = score
        out.append(new_f)
    return out


def run(label, fires, q_map, max_strength, start, end):
    t0 = time.time()
    cands = reranked(fires, q_map, max_strength)
    state = P.simulate(
        cands, start, end,
        initial_cash=10_000_000.0,
        max_positions=50,
        stop_loss_pct=0.0,
    )
    m = compute_full_metrics(state, start, end)
    sh = m["sharpe"] or 0
    so = m["sortino"] or 0
    ca = m["calmar"] or 0
    print(f"{label:<30s} n_tr={len(state.trades):>5}  "
          f"CAGR={m['annualised_return_pct']:>+6.2f}%  "
          f"Sh={sh:.3f}  So={so:.3f}  Ca={ca:.3f}  "
          f"DD={m['max_drawdown_mtm_pct']:>5.1f}%  "
          f"α={m.get('alpha_annual_pct') or 0:>+5.2f}%  "
          f"[{time.time()-t0:.0f}s]", flush=True)
    return m


def main():
    fires_csv = ROOT / "data" / "sweep_all_24w.csv"
    print(f"loading fires from {fires_csv} ...", flush=True)
    fires = P.load_fires_csv(fires_csv)
    fires = P.filter_entry_fires(fires, P.DEFAULT_ENTRY_SIGNALS)
    max_strength = max(float(f.get("strength", 0)) for f in fires)
    print(f"  {len(fires):,} entry candidates, max_strength={max_strength:.3f}",
          flush=True)

    defs = [
        "Q0_quality_safety",
        "Q1_quality_only",
        "Q2_safety_only",
        "Q3_buffett_gate",
        "Q4_all_factors",
    ]

    start = date(2009, 1, 1)
    end   = date(2026, 5, 22)

    print(f"\nWeighting fixed at: {BOOK_WEIGHT:.0%} book / {QUALITY_WEIGHT:.0%} q",
          flush=True)
    print(f"{'Q definition':<30s} {'trades':>6}  {'CAGR':>8}  "
          f"{'Sharpe':>6}  {'Sortino':>7}  {'Calmar':>6}  "
          f"{'DD':>6}  {'alpha':>6}", flush=True)
    print("-" * 105, flush=True)

    results = []
    for defn in defs:
        q_map = load_q_map(defn)
        covered = sum(1 for f in fires if f["ticker"] in q_map and q_map[f["ticker"]] > 0)
        print(f"  {defn}: {len(q_map):,} tickers, coverage on fires: "
              f"{covered:,} ({covered/len(fires)*100:.0f}%)", flush=True)
        m = run(defn, fires, q_map, max_strength, start, end)
        results.append((defn, m))

    out_csv = ROOT / "data" / "grid_search_q_definition_results.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["q_definition", "book_w", "quality_w",
                    "cagr_pct", "sharpe", "sortino", "calmar",
                    "max_dd_mtm_pct", "alpha_annual_pct",
                    "total_return_pct", "win_rate", "payoff"])
        for defn, m in results:
            w.writerow([defn, BOOK_WEIGHT, QUALITY_WEIGHT,
                        m.get("annualised_return_pct"),
                        m.get("sharpe"), m.get("sortino"),
                        m.get("calmar"), m.get("max_drawdown_mtm_pct"),
                        m.get("alpha_annual_pct"),
                        m.get("total_return_pct"),
                        m.get("win_rate"), m.get("payoff")])
    print(f"\nwrote {out_csv}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
