"""Phase 4 grid search — market-cap based quality variants.

Builds on Phase 3 winners. q definitions use market_cap_today (from
data/market_caps_today.csv crawled by crawl_market_caps.py).

Lookahead caveat: today's cap snapshot applied to 17y backtest. Same
trade-off as Phase 1+2's factors_eval quality. Directional, not bit-exact.

Variants (all weight 80% book / 20% q unless noted):

  L1: Large-cap bias    — q = min(log10(cap/1e10)/log10(1e3), 1)
                          (zero at <100억, full at ≥10조)
  L2: Mid-cap sweet     — q peaks at 3000억, taper to 0 at <100억 or >10조
  L3: Small-cap premium — q = 1 - L1
  L4: Microcap penalty + Q0
                        — q = Q0 if cap ≥ 500억, 0 otherwise
                          (filter, then quality+safety inside survivors)
  L5: Liquidity floor (binary)
                        — q = 1.0 if cap ≥ 500억, 0 otherwise
                          (cap alone, no quality)

Also runs B0 reference re-test (Q0 baseline 80/20) for direct comparison
since this is a new candidate set after cap filtering.
"""
from __future__ import annotations

import csv
import math
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

CAPS_CSV = ROOT / "data" / "market_caps_today.csv"

# Thresholds in KRW
CAP_MICRO  = 5e10    # 500억 — below = microcap (high risk)
CAP_SMALL  = 1e11    # 1000억 — small-cap boundary
CAP_MID_LO = 3e11    # 3000억 — mid-cap sweet-spot lower
CAP_MID_HI = 1e12    # 1조 — mid-cap sweet-spot peak
CAP_LARGE  = 1e13    # 10조 — large-cap floor


def load_cap_map() -> dict[str, float]:
    """Returns {ticker: cap_krw} from the crawled CSV. Skips empty rows."""
    out: dict[str, float] = {}
    with CAPS_CSV.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            v = row.get("market_cap_krw") or ""
            if v.strip():
                try:
                    out[row["ticker"]] = float(v)
                except ValueError:
                    pass
    return out


def load_q0_map() -> dict[str, float]:
    """Phase 2's Q0: (quality + safety) / 20."""
    out: dict[str, float] = {}
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT ticker, "
            "       (COALESCE(quality_score,0) + COALESCE(safety_score,0)) / 20.0 "
            "FROM factors_eval "
            "WHERE quality_score IS NOT NULL AND safety_score IS NOT NULL"
        )
        for ticker, val in cur.fetchall():
            out[ticker] = float(val) if val is not None else 0.0
    return out


def cap_to_q(definition: str, cap_map: dict[str, float],
             q0_map: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for t, cap in cap_map.items():
        if cap is None or cap <= 0:
            continue
        if definition == "L1_large_cap":
            # log scale: 100억 → 0, 10조 → 1, beyond → clipped 1
            x = math.log10(cap / 1e10) / math.log10(1e3)  # 1e13/1e10 = 1e3
            out[t] = max(0.0, min(1.0, x))
        elif definition == "L2_mid_cap_sweet":
            # tent shape on log-cap: peak at sqrt(CAP_MID_LO*CAP_MID_HI) ≈ 5470억
            log_cap = math.log10(cap)
            log_lo  = math.log10(CAP_MICRO)   # 5e10
            log_peak = (math.log10(CAP_MID_LO) + math.log10(CAP_MID_HI)) / 2
            log_hi  = math.log10(CAP_LARGE)   # 1e13
            if log_cap <= log_lo or log_cap >= log_hi:
                out[t] = 0.0
            elif log_cap <= log_peak:
                out[t] = (log_cap - log_lo) / (log_peak - log_lo)
            else:
                out[t] = (log_hi - log_cap) / (log_hi - log_peak)
        elif definition == "L3_small_cap":
            x = math.log10(cap / 1e10) / math.log10(1e3)
            out[t] = max(0.0, min(1.0, 1.0 - x))
        elif definition == "L4_micro_penalty_Q0":
            if cap < CAP_MICRO:
                out[t] = 0.0
            else:
                out[t] = q0_map.get(t, 0.0)
        elif definition == "L5_liquidity_floor":
            out[t] = 1.0 if cap >= CAP_MICRO else 0.0
        elif definition == "B0_Q0_reference":
            out[t] = q0_map.get(t, 0.0)
        else:
            raise ValueError(f"unknown definition: {definition}")
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
    if not CAPS_CSV.exists():
        print(f"missing {CAPS_CSV} — run scripts/crawl_market_caps.py first",
              flush=True)
        return 1

    fires_csv = ROOT / "data" / "sweep_all_24w.csv"
    print(f"loading fires from {fires_csv} ...", flush=True)
    fires = P.load_fires_csv(fires_csv)
    fires = P.filter_entry_fires(fires, P.DEFAULT_ENTRY_SIGNALS)
    max_strength = max(float(f.get("strength", 0)) for f in fires)
    print(f"  {len(fires):,} entry candidates, max_strength={max_strength:.3f}",
          flush=True)

    cap_map = load_cap_map()
    q0_map = load_q0_map()
    print(f"  cap_map: {len(cap_map):,} tickers (today's market cap)",
          flush=True)
    print(f"  q0_map:  {len(q0_map):,} tickers", flush=True)

    # Quick cap distribution
    caps = sorted(cap_map.values())
    if caps:
        n = len(caps)
        print(f"  cap p10/p50/p90: {caps[n//10]:.2e} / {caps[n//2]:.2e} / "
              f"{caps[9*n//10]:.2e} (KRW)", flush=True)

    variants = [
        # (label,                  book_w, quality_w, q_definition)
        ("B0_Q0_reference",        0.80, 0.20, "B0_Q0_reference"),
        ("L1_large_cap",           0.80, 0.20, "L1_large_cap"),
        ("L2_mid_cap_sweet",       0.80, 0.20, "L2_mid_cap_sweet"),
        ("L3_small_cap",           0.80, 0.20, "L3_small_cap"),
        ("L4_micro_penalty_Q0",    0.80, 0.20, "L4_micro_penalty_Q0"),
        ("L5_liquidity_floor",     0.80, 0.20, "L5_liquidity_floor"),
    ]

    start = date(2009, 1, 1)
    end   = date(2026, 5, 22)

    print(f"\n{'Variant':<28s} {'trades':>6}  {'CAGR':>8}  "
          f"{'Sharpe':>6}  {'Sortino':>7}  {'Calmar':>6}  "
          f"{'DD':>6}  {'alpha':>6}", flush=True)
    print("-" * 105, flush=True)

    results = []
    for label, bw, qw, defn in variants:
        q_map = cap_to_q(defn, cap_map, q0_map)
        nonzero = sum(1 for v in q_map.values() if v > 0)
        covered = sum(1 for f in fires
                      if f["ticker"] in q_map and q_map[f["ticker"]] > 0)
        print(f"  {label} ({defn}): {nonzero:,} tickers nonzero, "
              f"coverage on fires: {covered:,} ({covered/len(fires)*100:.0f}%)",
              flush=True)
        m = run(label, fires, q_map, bw, qw, max_strength, start, end)
        results.append((label, bw, qw, defn, m))

    out_csv = ROOT / "data" / "grid_search_phase4_results.csv"
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
