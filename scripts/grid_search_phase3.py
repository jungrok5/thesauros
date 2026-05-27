"""Phase 3 grid search — 8 selected variants (orthodox + contrarian).

After Phase 1 (winner V2: 80% book / 20% q) and Phase 2 (winner Q0:
quality+safety):

Orthodox extensions:
  A1: 90% book / 10% q (Q0)          — weight precision: less q
  A2: 85% book / 15% q (Q0)          — weight precision: sweet spot
  A4: 80% book / 20% q (Q3 Buffett)  — Phase 2 Sharpe champ at V2 weight
  A5: 80/20 with Magic Formula gate  — alt value gate (Greenblatt)

Contrarian (역발상):
  B1: Inverse quality (1 - q/10)      — buy LOW quality (mean reversion)
  B3: Mid-quality only (1 - 2|q-0.5|) — anti-extremes (sweet middle)
  B6: Quality × Value (continuous)    — Magic-Formula spirit, no gate
  B9: Random q seed=42                — null hypothesis / sanity check

All variants use weight 80/20 except A1, A2.
"""
from __future__ import annotations

import csv
import random
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


def load_q_map(definition: str, seed: int = 42) -> dict[str, float]:
    """Returns {ticker: q in [0,1]} for the given definition."""
    if definition == "B9_random_seed42":
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT DISTINCT ticker FROM factors_eval")
            tickers = sorted(t for (t,) in cur.fetchall())
        rng = random.Random(seed)
        return {t: rng.random() for t in tickers}

    sql_by_def = {
        "Q0_quality_safety":
            "SELECT ticker, "
            "       (COALESCE(quality_score,0) + COALESCE(safety_score,0)) / 20.0 "
            "FROM factors_eval "
            "WHERE quality_score IS NOT NULL AND safety_score IS NOT NULL",
        "Q3_buffett_gate":
            "SELECT ticker, CASE WHEN passes_buffett THEN 1.0 ELSE 0.0 END "
            "FROM factors_eval",
        "A5_magic_gate":
            "SELECT ticker, CASE WHEN passes_magic_formula THEN 1.0 ELSE 0.0 END "
            "FROM factors_eval",
        "B1_inverse_quality":
            "SELECT ticker, 1.0 - COALESCE(quality_score,0)/10.0 "
            "FROM factors_eval WHERE quality_score IS NOT NULL",
        "B3_mid_quality":
            "SELECT ticker, "
            "       1.0 - 2.0*ABS((COALESCE(quality_score,0)+COALESCE(safety_score,0))/20.0 - 0.5) "
            "FROM factors_eval "
            "WHERE quality_score IS NOT NULL AND safety_score IS NOT NULL",
        "B6_quality_x_value":
            "SELECT ticker, "
            "       (COALESCE(quality_score,0)/10.0) * (COALESCE(value_score,0)/10.0) "
            "FROM factors_eval "
            "WHERE quality_score IS NOT NULL AND value_score IS NOT NULL",
    }
    sql = sql_by_def[definition]
    out: dict[str, float] = {}
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql)
        for ticker, val in cur.fetchall():
            out[ticker] = float(val) if val is not None else 0.0
    return out


def reranked(fires, q_map, book_w, quality_w, max_strength):
    out = []
    for f in fires:
        s = float(f.get("strength", 0))
        s_n = s / max_strength if max_strength > 0 else 0
        q = q_map.get(f["ticker"], 0)
        score = book_w * s_n + quality_w * q
        new_f = dict(f)
        new_f["strength"] = score
        out.append(new_f)
    return out


def run(label, fires, q_map, book_w, quality_w, max_strength, start, end):
    t0 = time.time()
    cands = reranked(fires, q_map, book_w, quality_w, max_strength)
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
    print(f"{label:<28s} n_tr={len(state.trades):>5}  "
          f"CAGR={m['annualised_return_pct']:>+6.2f}%  "
          f"Sh={sh:.3f}  So={so:.3f}  Ca={ca:.3f}  "
          f"DD={m['max_drawdown_mtm_pct']:>5.1f}%  "
          f"α={m.get('alpha_annual_pct') or 0:>+5.2f}%  "
          f"[{time.time()-t0:.0f}s]", flush=True)
    return m


def main() -> int:
    fires_csv = ROOT / "data" / "sweep_all_24w.csv"
    print(f"loading fires from {fires_csv} ...", flush=True)
    fires = P.load_fires_csv(fires_csv)
    fires = P.filter_entry_fires(fires, P.DEFAULT_ENTRY_SIGNALS)
    max_strength = max(float(f.get("strength", 0)) for f in fires)
    print(f"  {len(fires):,} entry candidates, max_strength={max_strength:.3f}",
          flush=True)

    variants = [
        # (label,                  book_w, quality_w, q_definition)
        ("A1_90_10_Q0",            0.90, 0.10, "Q0_quality_safety"),
        ("A2_85_15_Q0",            0.85, 0.15, "Q0_quality_safety"),
        ("A4_80_20_Q3_buffett",    0.80, 0.20, "Q3_buffett_gate"),
        ("A5_magic_formula_gate",  0.80, 0.20, "A5_magic_gate"),
        ("B1_inverse_quality",     0.80, 0.20, "B1_inverse_quality"),
        ("B3_mid_quality",         0.80, 0.20, "B3_mid_quality"),
        ("B6_quality_x_value",     0.80, 0.20, "B6_quality_x_value"),
        ("B9_random_seed42",       0.80, 0.20, "B9_random_seed42"),
    ]

    start = date(2009, 1, 1)
    end   = date(2026, 5, 22)

    print(f"\n{'Variant':<28s} {'trades':>6}  {'CAGR':>8}  "
          f"{'Sharpe':>6}  {'Sortino':>7}  {'Calmar':>6}  "
          f"{'DD':>6}  {'alpha':>6}", flush=True)
    print("-" * 105, flush=True)

    results = []
    for label, bw, qw, defn in variants:
        q_map = load_q_map(defn)
        covered = sum(1 for f in fires if f["ticker"] in q_map and q_map[f["ticker"]] > 0)
        print(f"  {label} ({defn}): {len(q_map):,} tickers, "
              f"coverage on fires: {covered:,} ({covered/len(fires)*100:.0f}%)",
              flush=True)
        m = run(label, fires, q_map, bw, qw, max_strength, start, end)
        results.append((label, bw, qw, defn, m))

    out_csv = ROOT / "data" / "grid_search_phase3_results.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["variant", "book_w", "quality_w", "q_definition",
                    "cagr_pct", "sharpe", "sortino", "calmar",
                    "max_dd_mtm_pct", "alpha_annual_pct",
                    "total_return_pct", "win_rate", "payoff"])
        for label, bw, qw, defn, m in results:
            w.writerow([label, bw, qw, defn,
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
