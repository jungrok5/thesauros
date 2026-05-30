"""Phase 11 — Macro regime gate on top of book-faithful production.

Book p318-319: "월봉 10이평선이 바로 객관적 추세선". Already
implemented as `app.backtest.market_regime.kospi_regime_filter` and
`kospi_smart_filter`. This script measures the lift over the
book-faithful baseline + walk-forward audit.

Variants:
  P11_00_baseline         no regime gate (current production)
  P11_10_strict           KOSPI monthly close < 10MA → block BUY
  P11_20_smart_3pct       smart filter: below ≥3% AND MA falling
  P11_21_smart_5pct       smart filter: below ≥5% AND MA falling
  P11_22_smart_3pct_anyslope  below ≥3%, slope ignored

Walk-forward: train 2009-2017 → test 2018-2026, same protocol as
project_book_faithful_backtest.

Output:
  data/phase11_summary.csv
  data/phase11_walk_forward.csv
"""
from __future__ import annotations

import csv
import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.backtest import portfolio as P
from app.backtest.metrics import compute_full_metrics
from app.backtest.portfolio_book import simulate_book_faithful, reset_caches
from app.backtest.market_regime import (
    kospi_regime_filter, kospi_smart_filter, clear_regime_cache,
)
from scripts.grid_phase5_factors import (
    apply_variant, load_cap_map, load_sector_map, LiquidityLookup,
)


# ─────────────────────────────────────────────────────────────────────
# Regime variants — each builds a (date) -> bool callable, or None.
# ─────────────────────────────────────────────────────────────────────
def _no_gate() -> Optional[Callable[[date], bool]]:
    return None


def _strict() -> Callable[[date], bool]:
    return kospi_regime_filter(allow_unknown=True)


def _smart(below_pct: float, falling: bool) -> Callable[[date], bool]:
    return kospi_smart_filter(
        below_threshold_pct=below_pct,
        require_falling_ma=falling,
        allow_unknown=True,
    )


VARIANTS: Dict[str, Callable[[], Optional[Callable[[date], bool]]]] = {
    "P11_00_baseline":            _no_gate,
    "P11_10_strict":              _strict,
    "P11_20_smart_3pct":          lambda: _smart(3.0, True),
    "P11_21_smart_5pct":          lambda: _smart(5.0, True),
    "P11_22_smart_3pct_anyslope": lambda: _smart(3.0, False),
}


# ─────────────────────────────────────────────────────────────────────
# Shared sim wiring
# ─────────────────────────────────────────────────────────────────────
def _load_inputs():
    fires = P.load_fires_csv(ROOT / "data" / "sweep_all_24w.csv")
    fires = P.filter_entry_fires(fires, P.DEFAULT_ENTRY_SIGNALS)
    max_strength = max(float(f.get("strength", 0)) for f in fires)
    cap_map = load_cap_map()
    sector_map = load_sector_map()
    liquidity = LiquidityLookup()
    cands = apply_variant(
        fires, cap_map, sector_map, max_strength,
        sector_cap_per_week=1, book_weight=1.0,
    )
    exit_fires_all = P.load_fires_csv(ROOT / "data" / "sweep_all_24w.csv")
    exit_fires = [
        f for f in exit_fires_all
        if f.get("signal_type") in P.DEFAULT_EXIT_SIGNALS
        and f.get("timeframe") == "weekly"
    ]
    return cands, exit_fires


def _run(
    key: str, gate: Optional[Callable[[date], bool]],
    cands, exit_fires, start: date, end: date,
) -> Dict[str, Any]:
    print(f"\n[{key}] start={start} end={end} gate={'on' if gate else 'off'}",
          flush=True)
    reset_caches()
    clear_regime_cache()
    t0 = time.time()
    state = simulate_book_faithful(
        cands, start, end,
        initial_cash=100_000_000.0,
        max_positions=20,
        exit_fires=exit_fires,
        regime_filter=gate,
    )
    m = compute_full_metrics(state, start, end)
    print(f"  done {time.time()-t0:.0f}s: trades={len(state.trades):,} "
          f"CAGR={m['annualised_return_pct']:+.2f} "
          f"Sharpe={m['sharpe']:.2f} "
          f"DD={m['max_drawdown_mtm_pct']:.1f} "
          f"Alpha={m.get('alpha_annual_pct'):+.2f}", flush=True)
    return {
        "key": key,
        "n_trades": len(state.trades),
        "cagr": m["annualised_return_pct"],
        "sharpe": m["sharpe"],
        "sortino": m["sortino"],
        "calmar": m["calmar"],
        "max_dd": m["max_drawdown_mtm_pct"],
        "alpha_ann": m.get("alpha_annual_pct"),
        "outperf_ann": m.get("outperformance_ann_pct"),
    }


def main() -> int:
    print("loading inputs ...", flush=True)
    cands, exit_fires = _load_inputs()
    print(f"  cands={len(cands):,} exit_fires={len(exit_fires):,}", flush=True)

    # ── Full-period sweep (in-sample) ──
    print("\n=== FULL PERIOD 2009-2026 (in-sample) ===", flush=True)
    full = []
    for key, build in VARIANTS.items():
        full.append(_run(key, build(), cands, exit_fires,
                         date(2009, 1, 1), date(2026, 5, 22)))

    # ── Walk-forward: train + test fold ──
    print("\n=== WALK-FORWARD train 2009-2017 / test 2018-2026 ===",
          flush=True)
    train, test = [], []
    for key, build in VARIANTS.items():
        train.append({**_run(f"{key}@train", build(), cands, exit_fires,
                             date(2009, 1, 1), date(2017, 12, 31)),
                      "fold": "train"})
        test.append({**_run(f"{key}@test", build(), cands, exit_fires,
                            date(2018, 1, 1), date(2026, 5, 22)),
                     "fold": "test"})

    # ── Save ──
    full_csv = ROOT / "data" / "phase11_summary.csv"
    with full_csv.open("w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=list(full[0].keys()))
        w.writeheader(); w.writerows(full)
    print(f"\nwrote {full_csv}", flush=True)

    wf_csv = ROOT / "data" / "phase11_walk_forward.csv"
    with wf_csv.open("w", encoding="utf-8", newline="") as fp:
        rows = train + test
        w = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"wrote {wf_csv}", flush=True)

    # ── Ranking by Sharpe (full period) ──
    full.sort(key=lambda r: -(r["sharpe"] or 0))
    print("\n── FULL PERIOD RANKING (Sharpe desc) ──")
    print(f"  {'variant':<32} {'CAGR':>8} {'Sharpe':>7} {'DD':>7} {'Alpha':>8} trades")
    for r in full:
        print(f"  {r['key']:<32} {r['cagr']:+7.2f}% "
              f"{r['sharpe']:6.2f} {r['max_dd']:6.1f}% "
              f"{r.get('alpha_ann'):+7.2f}% {r['n_trades']:>6}")

    # ── OOS verdict ──
    print("\n── WALK-FORWARD VERDICT ──")
    baseline_test = next(r for r in test if r["key"] == "P11_00_baseline@test")
    print(f"  baseline@test: CAGR {baseline_test['cagr']:+.2f}  "
          f"Sharpe {baseline_test['sharpe']:.2f}  Alpha {baseline_test['alpha_ann']:+.2f}")
    for r in test:
        if r["key"] == "P11_00_baseline@test":
            continue
        d_cagr = r["cagr"] - baseline_test["cagr"]
        d_sh = r["sharpe"] - baseline_test["sharpe"]
        d_alpha = (r["alpha_ann"] or 0) - (baseline_test["alpha_ann"] or 0)
        verdict = (
            "✓ PASS" if (d_cagr > 0.5 or d_alpha > 0.5) and d_sh > -0.02
            else "✗ FAIL"
        )
        print(f"  {r['key']:<35} ΔCAGR {d_cagr:+.2f}pp  "
              f"ΔSharpe {d_sh:+.3f}  ΔAlpha {d_alpha:+.2f}pp  {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
