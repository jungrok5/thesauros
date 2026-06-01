"""Phase 12 — Kelly fractional sizing on top of book-faithful baseline.

Hypothesis: weighting per-signal capital allocation by each signal's
historical edge (Kelly fraction) lifts CAGR / Sharpe vs uniform max/N
allocation.

Look-ahead trap to avoid: if we estimate signal stats on the FULL
period 2009-2026 and apply them to the same period, that's circular
(in-sample weights → in-sample lift). The honest walk-forward:

  TRAIN 2009-2017 — run book-faithful baseline. Tabulate per-signal
                    win-rate, avg_win_pct, avg_loss_pct → compute
                    Kelly fraction = (p × W − (1-p) × L) / W.
                    Clip to fractional-Kelly band.
  TEST  2018-2026 — re-run book-faithful with the TRAIN-derived
                    weights as `signal_weight_map`. Compare to test-
                    baseline. The weights NEVER see the test data.

Variants:
  P12_00_baseline                 uniform max/N allocation
  P12_10_kelly_quarter             fractional-Kelly × 0.25 per signal
  P12_11_kelly_half                fractional-Kelly × 0.50
  P12_12_kelly_full                full Kelly (× 1.00, capped at 1.5)
  P12_20_uniform_by_avg            weight by avg_return_pct (no Kelly math)
"""
from __future__ import annotations

import csv
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.backtest import portfolio as P
from app.backtest.metrics import compute_full_metrics
from app.backtest.portfolio_book import (
    simulate_book_faithful, reset_caches, PortfolioState, Position, Trade,
    _BUY_COST_PCT, _SELL_COST_PCT,
)
from scripts.grid_phase5_factors import (
    apply_variant, load_cap_map, load_sector_map, LiquidityLookup,
)


# ─────────────────────────────────────────────────────────────────────
# 1) Per-signal stats from a state.trades list
# ─────────────────────────────────────────────────────────────────────
def per_signal_stats(state: PortfolioState) -> Dict[str, Dict[str, float]]:
    by_sig: Dict[str, List[float]] = defaultdict(list)
    for t in state.trades:
        # signal_type is "<entry_sig>→<exit_sig>"; we want the entry side.
        entry_sig = t.signal_type.split("→")[0] if "→" in t.signal_type else t.signal_type
        by_sig[entry_sig].append(t.pnl_pct)
    out: Dict[str, Dict[str, float]] = {}
    for sig, returns in by_sig.items():
        if not returns:
            continue
        wins = [r for r in returns if r > 0]
        losses = [-r for r in returns if r < 0]
        p = len(wins) / len(returns)
        avg_w = sum(wins) / len(wins) if wins else 0.0
        avg_l = sum(losses) / len(losses) if losses else 0.0
        # Kelly fraction f* = (p × W − (1−p) × L) / W
        kelly = ((p * avg_w) - ((1 - p) * avg_l)) / avg_w if avg_w > 0 else 0.0
        out[sig] = {
            "n": len(returns),
            "winrate": p,
            "avg_win_pct": avg_w,
            "avg_loss_pct": avg_l,
            "avg_return_pct": sum(returns) / len(returns),
            "kelly": kelly,
        }
    return out


# ─────────────────────────────────────────────────────────────────────
# 2) Simulator with per-signal allocation multiplier.
#    Same event loop as simulate_book_faithful but multiplies the
#    per-BUY allocation by signal_weight_map.get(signal, 1.0). Capped
#    at 1.0 (never exceed the equal-split share).
# ─────────────────────────────────────────────────────────────────────
def simulate_book_faithful_weighted(
    candidates,
    start_date: date,
    end_date: date,
    *,
    initial_cash: float = 100_000_000.0,
    max_positions: int = 20,
    exit_fires=None,
    signal_weight_map: Optional[Dict[str, float]] = None,
    weight_cap: float = 1.0,
) -> PortfolioState:
    """Re-implements simulate_book_faithful with one tweak: BUY
    allocation gets a per-signal multiplier."""
    from app.backtest.portfolio_book import (
        _build_monthly_10ma_exit_events,
        _build_quartile_exit_events,
        _equity_estimate,
    )

    events: List[Tuple[date, str, str, float, int, float]] = []
    cand_lookup: Dict[int, Dict[str, Any]] = {}
    for i, c in enumerate(candidates):
        ed = date.fromisoformat(c["entry_date"])
        if ed < start_date or ed > end_date:
            continue
        cand_lookup[i] = c
        strength = float(c.get("strength", 0.5))
        events.append((ed, "BUY", c["ticker"],
                      float(c["entry_price"]), i, strength))

    filtered = [cand_lookup[i] for i in cand_lookup]
    events.extend(_build_monthly_10ma_exit_events(filtered, start_date, end_date))
    events.extend(_build_quartile_exit_events(filtered, start_date, end_date))

    exit_sig_lookup: Dict[Tuple[str, str], str] = {}
    if exit_fires:
        for f in exit_fires:
            ed = date.fromisoformat(f["entry_date"])
            if ed < start_date or ed > end_date:
                continue
            events.append((ed, "ACTIVE_EXIT", f["ticker"],
                          float(f["entry_price"]), -1, 0.0))
            exit_sig_lookup[(f["ticker"], f["entry_date"])] = f.get(
                "signal_type", "exit"
            )

    def _order(e):
        kind_rank = {"ACTIVE_EXIT": 0, "EXIT_10MA": 1,
                     "EXIT_QUARTILE": 2, "BUY": 3}.get(e[1], 4)
        return (e[0], kind_rank, -e[5] if e[1] == "BUY" else 0.0)
    events.sort(key=_order)

    state = PortfolioState(cash=initial_cash, initial_cash=initial_cash)

    def _close_position(d, ticker, price, entry_sig, exit_sig):
        pos = state.positions.pop(ticker)
        proceeds = pos.shares * price * (1 - _SELL_COST_PCT)
        state.cash += proceeds
        pnl = proceeds - pos.cost_basis_krw
        state.trades.append(Trade(
            ticker=ticker, entry_date=pos.entry_date, exit_date=d,
            entry_price=pos.entry_price, exit_price=price,
            shares=pos.shares, cost_basis_krw=pos.cost_basis_krw,
            proceeds_krw=proceeds, pnl_krw=pnl,
            pnl_pct=(pnl / pos.cost_basis_krw * 100.0)
                    if pos.cost_basis_krw > 0 else 0.0,
            days_held=(d - pos.entry_date).days,
            signal_type=f"{entry_sig}→{exit_sig}" if exit_sig else entry_sig,
        ))
        state.equity_history.append((d, _equity_estimate(state)))

    for d, kind, ticker, price, cand_idx, _s in events:
        if kind in ("ACTIVE_EXIT", "EXIT_10MA", "EXIT_QUARTILE"):
            if ticker not in state.positions:
                continue
            entry_sig = state.positions[ticker].entry_signal
            if kind == "ACTIVE_EXIT":
                exit_label = exit_sig_lookup.get(
                    (ticker, d.isoformat()), "active_exit"
                )
            elif kind == "EXIT_10MA":
                exit_label = "monthly_10ma_break"
            else:
                exit_label = "quartile_25_break"
            _close_position(d, ticker, price, entry_sig, exit_label)
        elif kind == "BUY":
            if len(state.positions) >= max_positions:
                continue
            if ticker in state.positions:
                continue
            open_slots = max_positions - len(state.positions)
            if open_slots <= 0:
                continue
            cand = cand_lookup[cand_idx]
            sig = cand.get("signal_type", "?")
            weight = (
                signal_weight_map.get(sig, 1.0)
                if signal_weight_map else 1.0
            )
            weight = max(0.0, min(weight_cap, weight))
            allocation = (state.cash / open_slots) * weight
            if allocation <= 0 or price <= 0:
                continue
            net = allocation / (1 + _BUY_COST_PCT)
            shares = net / price
            cost_basis = allocation
            if shares <= 0:
                continue
            state.cash -= cost_basis
            state.positions[ticker] = Position(
                ticker=ticker, entry_date=d, entry_price=price,
                shares=shares, cost_basis_krw=cost_basis,
                exit_date_planned=end_date,
                entry_signal=sig,
            )
            state.equity_history.append((d, _equity_estimate(state)))

    # Mark-to-market.
    from app.backtest.portfolio import _last_close_or_na
    for ticker, pos in list(state.positions.items()):
        final_price = _last_close_or_na(ticker, end_date) or pos.entry_price
        proceeds = pos.shares * final_price * (1 - _SELL_COST_PCT)
        state.cash += proceeds
        pnl = proceeds - pos.cost_basis_krw
        state.trades.append(Trade(
            ticker=ticker, entry_date=pos.entry_date, exit_date=end_date,
            entry_price=pos.entry_price, exit_price=final_price,
            shares=pos.shares, cost_basis_krw=pos.cost_basis_krw,
            proceeds_krw=proceeds, pnl_krw=pnl,
            pnl_pct=(pnl / pos.cost_basis_krw * 100.0)
                    if pos.cost_basis_krw > 0 else 0.0,
            days_held=(end_date - pos.entry_date).days,
            signal_type=f"{pos.entry_signal}→forced_close_at_end",
        ))
        del state.positions[ticker]
    state.equity_history.append((end_date, _equity_estimate(state)))
    return state


# ─────────────────────────────────────────────────────────────────────
# 3) Driver
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


def _scale_kelly(stats: Dict[str, Dict[str, float]], mult: float,
                 cap: float = 1.5) -> Dict[str, float]:
    """fractional Kelly × mult, clipped to [0, cap]."""
    out: Dict[str, float] = {}
    for sig, s in stats.items():
        f = max(0.0, s["kelly"]) * mult
        out[sig] = min(cap, f)
    return out


def _scale_by_avg(stats: Dict[str, Dict[str, float]],
                  baseline_avg: float) -> Dict[str, float]:
    """uniform-by-avg: weight = avg_return / baseline_avg, clipped [0.5, 1.5]."""
    out: Dict[str, float] = {}
    for sig, s in stats.items():
        if baseline_avg <= 0:
            out[sig] = 1.0; continue
        w = s["avg_return_pct"] / baseline_avg
        out[sig] = max(0.5, min(1.5, w))
    return out


def _run(
    key: str, weights: Optional[Dict[str, float]], cands, exit_fires,
    start: date, end: date,
) -> Dict[str, Any]:
    print(f"\n[{key}] start={start} end={end} weighted={'on' if weights else 'off'}",
          flush=True)
    reset_caches()
    t0 = time.time()
    state = simulate_book_faithful_weighted(
        cands, start, end,
        initial_cash=100_000_000.0,
        max_positions=20,
        exit_fires=exit_fires,
        signal_weight_map=weights,
    )
    m = compute_full_metrics(state, start, end)
    print(f"  done {time.time()-t0:.0f}s: trades={len(state.trades):,} "
          f"CAGR={m['annualised_return_pct']:+.2f} "
          f"Sharpe={m['sharpe']:.2f} "
          f"Alpha={m.get('alpha_annual_pct'):+.2f}", flush=True)
    return {
        "key": key,
        "n_trades": len(state.trades),
        "cagr": m["annualised_return_pct"],
        "sharpe": m["sharpe"],
        "max_dd": m["max_drawdown_mtm_pct"],
        "alpha_ann": m.get("alpha_annual_pct"),
        "state": state,
    }


def main() -> int:
    print("loading inputs ...", flush=True)
    cands, exit_fires = _load_inputs()
    print(f"  cands={len(cands):,} exit_fires={len(exit_fires):,}", flush=True)

    # STEP 1: Train fold — baseline (uniform), estimate per-signal stats
    print("\n=== TRAIN 2009-2017 — baseline run, then estimate weights ===",
          flush=True)
    train_baseline = _run("P12_train_baseline", None, cands, exit_fires,
                          date(2009, 1, 1), date(2017, 12, 31))
    stats = per_signal_stats(train_baseline["state"])
    print("\nper-signal stats from TRAIN fold:")
    print(f"  {'signal':<30} {'n':>5} {'winrate':>8} {'avg_w%':>7} "
          f"{'avg_l%':>7} {'avg_r%':>7} {'kelly':>7}")
    for sig, s in sorted(stats.items(), key=lambda x: -x[1]["kelly"]):
        print(f"  {sig:<30} {s['n']:>5} {s['winrate']:>7.1%} "
              f"{s['avg_win_pct']:>+6.2f} {-s['avg_loss_pct']:>+6.2f} "
              f"{s['avg_return_pct']:>+6.2f} {s['kelly']:>+6.2f}")
    baseline_train_avg = (
        train_baseline["state"].equity_history[-1][1]
        / train_baseline["state"].initial_cash - 1
    ) * 100 / 9.0
    print(f"  (baseline train avg return per year: {baseline_train_avg:+.2f}%)",
          flush=True)

    # STEP 2: Variants — weights derived ONLY from train, applied to both folds
    weights_variants: Dict[str, Optional[Dict[str, float]]] = {
        "P12_00_baseline":      None,                                   # uniform
        "P12_10_kelly_quarter": _scale_kelly(stats, 0.25),
        "P12_11_kelly_half":    _scale_kelly(stats, 0.50),
        "P12_12_kelly_full":    _scale_kelly(stats, 1.00),
        "P12_20_uniform_by_avg":
            _scale_by_avg(stats, sum(s["avg_return_pct"] for s in stats.values()) / max(1, len(stats))),
    }
    print("\n=== APPLY TRAIN WEIGHTS → BOTH FOLDS (variants) ===", flush=True)
    rows: List[Dict[str, Any]] = []
    for key, w in weights_variants.items():
        for fold, s, e in [("train", date(2009, 1, 1), date(2017, 12, 31)),
                           ("test",  date(2018, 1, 1), date(2026, 5, 22))]:
            r = _run(f"{key}@{fold}", w, cands, exit_fires, s, e)
            r["fold"] = fold
            del r["state"]
            rows.append(r)

    # ── Save + report ──
    out_csv = ROOT / "data" / "phase12_walk_forward.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as fp:
        w_csv = csv.DictWriter(fp, fieldnames=[
            "fold", "key", "n_trades", "cagr", "sharpe", "max_dd", "alpha_ann",
        ])
        w_csv.writeheader()
        for r in rows:
            w_csv.writerow({k: r.get(k) for k in
                            ["fold", "key", "n_trades", "cagr",
                             "sharpe", "max_dd", "alpha_ann"]})
    print(f"\nwrote {out_csv}", flush=True)

    # OOS verdict
    print("\n── WALK-FORWARD VERDICT (TEST fold lifts over baseline) ──",
          flush=True)
    test_rows = [r for r in rows if r["fold"] == "test"]
    test_base = next(r for r in test_rows if r["key"] == "P12_00_baseline@test")
    print(f"  baseline@test: CAGR {test_base['cagr']:+.2f}  "
          f"Sharpe {test_base['sharpe']:.2f}  Alpha {test_base['alpha_ann']:+.2f}")
    any_pass = False
    for r in test_rows:
        if r["key"] == "P12_00_baseline@test":
            continue
        d_cagr = r["cagr"] - test_base["cagr"]
        d_sh = r["sharpe"] - test_base["sharpe"]
        d_alpha = (r["alpha_ann"] or 0) - (test_base["alpha_ann"] or 0)
        verdict = (
            "✓ PASS" if (d_cagr > 0.5 or d_alpha > 0.5) and d_sh > -0.02
            else "✗ FAIL"
        )
        if verdict.startswith("✓"):
            any_pass = True
        print(f"  {r['key']:<35} ΔCAGR {d_cagr:+.2f}pp  "
              f"ΔSharpe {d_sh:+.3f}  ΔAlpha {d_alpha:+.2f}pp  {verdict}")
    if not any_pass:
        print("  → All variants FAIL. Kelly sizing offers no OOS lift.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
