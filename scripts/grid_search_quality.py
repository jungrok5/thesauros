"""Grid-search backtest — book-spirit signal × quality re-ranking.

User asked (2026-05-27): "현재 ranking 1위가 fake 일 때 book_score 0.9 +
ROE 30% + 부채 10% 가 더 좋은 매수일 가능성. 다양한 가중을 historical
backtest 로 비교해서 best 찾아달라."

Approach
========

1. Load existing sweep_all_24w.csv (4.05M fires, 17 years).
2. Filter to entry signals (DEFAULT_ENTRY_SIGNALS).
3. Per fire, look up the ticker's quality_score + safety_score from
   factors_eval (today's snapshot — lookahead bias, documented).
4. For each variant of (book_weight, quality_weight):
     final_score = (book_w * strength / max_strength)
                 + (quality_w * (quality+safety)/MAX)
   replace `strength` with `final_score`, run portfolio.simulate
   with the production config (no-SL / max=50 / 24w / 10M cash),
   record CAGR / Sharpe / DD / win_rate / payoff.
5. Print result table.

Lookahead caveat
================
factors_eval is today's snapshot. Quality of a company in 2009
may differ from today. We assume quality is reasonably persistent
(Buffett 'moat' hypothesis) across 17 years. Results are
directional, not bit-exact predictions.

Usage:
    python scripts/grid_search_quality.py
"""
from __future__ import annotations

import csv
import sys
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import pandas as pd

# Make sure project root is on sys.path so `app.*` imports work.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.backtest import portfolio as P
from app.backtest.metrics import compute_full_metrics
from app.db.connection import get_conn


def load_quality_map() -> dict:
    """Returns {ticker: quality_value} for ranking.
    quality_value ∈ [0, 1] — normalized blend of quality_score + safety_score.

    factors_eval.quality_score range: 0~10ish (ROE+ROA+op_margin axes)
    factors_eval.safety_score   range: 0~10  (low debt)

    Combined (q + s) / 20 → [0, 1].
    """
    out: dict[str, float] = {}
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT ticker, quality_score, safety_score FROM factors_eval "
            "WHERE quality_score IS NOT NULL AND safety_score IS NOT NULL"
        )
        for ticker, q, s in cur.fetchall():
            out[ticker] = (float(q) + float(s)) / 20.0
    return out


def reranked_candidates(
    fires: list, quality_map: dict,
    book_w: float, quality_w: float, max_strength: float,
) -> list:
    """Compute final_score per fire, attach as 'strength' so the
    existing portfolio simulator's candidate ordering uses it."""
    out = []
    for f in fires:
        s = float(f.get("strength", 0))
        q = quality_map.get(f["ticker"], 0)   # missing → 0 (penalize)
        # Normalize strength to [0, 1] using max_strength (~1.0).
        s_n = s / max_strength if max_strength > 0 else 0
        score = book_w * s_n + quality_w * q
        new_f = dict(f)
        new_f["strength"] = score
        out.append(new_f)
    return out


def run_variant(
    label: str,
    fires: list,
    quality_map: dict,
    book_w: float,
    quality_w: float,
    max_strength: float,
    start: date,
    end: date,
):
    t0 = time.time()
    cands = reranked_candidates(fires, quality_map, book_w, quality_w, max_strength)
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
    elapsed = time.time() - t0
    print(f"{label:<35s} n_tr={len(state.trades):>5}  "
          f"CAGR={m['annualised_return_pct']:>+6.2f}%  "
          f"Sh={sh:.3f}  So={so:.3f}  Ca={ca:.3f}  "
          f"DD={m['max_drawdown_mtm_pct']:>5.1f}%  "
          f"α={m.get('alpha_annual_pct') or 0:>+5.2f}%  "
          f"[{elapsed:.0f}s]", flush=True)
    return m


def main() -> int:
    fires_csv = ROOT / "data" / "sweep_all_24w.csv"
    print(f"loading fires from {fires_csv} ...", flush=True)
    fires = P.load_fires_csv(fires_csv)
    fires = P.filter_entry_fires(fires, P.DEFAULT_ENTRY_SIGNALS)
    max_strength = max(float(f.get("strength", 0)) for f in fires)
    print(f"  {len(fires):,} entry candidates, max_strength={max_strength:.3f}",
          flush=True)

    print("loading quality_map from factors_eval ...", flush=True)
    quality_map = load_quality_map()
    print(f"  {len(quality_map):,} tickers with quality+safety scores",
          flush=True)

    # Coverage on the actual entry candidates.
    covered = sum(1 for f in fires if f["ticker"] in quality_map)
    print(f"  coverage: {covered:,} of {len(fires):,} fires "
          f"({covered/len(fires)*100:.0f}%)\n", flush=True)

    start = date(2009, 1, 1)
    end   = date(2026, 5, 22)

    variants = [
        # (label,                    book_w, quality_w)
        ("V0: book-only (baseline)",  1.0,   0.0),
        ("V1: quality-only",          0.0,   1.0),
        ("V2: 80% book / 20% q",      0.8,   0.2),
        ("V3: 60% book / 40% q",      0.6,   0.4),
        ("V4: 50% book / 50% q",      0.5,   0.5),
        ("V5: 40% book / 60% q",      0.4,   0.6),
        ("V6: 20% book / 80% q",      0.2,   0.8),
        ("V7: 70% book / 30% q",      0.7,   0.3),
    ]

    print(f"{'Variant':<35s} {'trades':>6}  {'CAGR':>8}  "
          f"{'Sharpe':>6}  {'Sortino':>7}  {'Calmar':>6}  "
          f"{'DD':>6}  {'alpha':>6}", flush=True)
    print("-" * 110, flush=True)

    results = []
    for label, bw, qw in variants:
        m = run_variant(label, fires, quality_map, bw, qw, max_strength, start, end)
        results.append((label, bw, qw, m))

    # Write CSV summary too.
    out_csv = ROOT / "data" / "grid_search_quality_results.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["variant", "book_w", "quality_w",
                    "cagr_pct", "sharpe", "sortino", "calmar",
                    "max_dd_mtm_pct", "alpha_annual_pct",
                    "total_return_pct", "win_rate", "payoff"])
        for label, bw, qw, m in results:
            w.writerow([label, bw, qw,
                        m.get("annualised_return_pct"),
                        m.get("sharpe"),
                        m.get("sortino"),
                        m.get("calmar"),
                        m.get("max_drawdown_mtm_pct"),
                        m.get("alpha_annual_pct"),
                        m.get("total_return_pct"),
                        m.get("win_rate"),
                        m.get("payoff")])
    print(f"\nwrote {out_csv}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
