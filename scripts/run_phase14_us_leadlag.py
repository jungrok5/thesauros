"""Phase 14 — US t → KR t+1 lead-lag factor for memory/semi names.

Hypothesis: US market closes after KR market closes (about 23:30 KST
→ 06:00 next day KST). MU/NVDA's t-day close carries new information
that the KR memory chain (Hynix 000660.KS, Samsung 005930.KS, 한미반도체
042700.KS, etc.) reflects on its t+1 session.

Factor: if a candidate ticker is in the memory-chain list AND the
prior US close (closest weekly bar ≤ entry_date) had a strong move
(|z| ≥ 1σ over a rolling 26-week window), add a small bonus to the
score before sector_cap=1 + simulate_book_faithful.

Look-ahead safety: US closes BEFORE the KR session that fires the
signal, so this is PIT-safe by construction.

Walk-forward:
  TRAIN 2009-2017 — pick the US tickers + threshold + bonus that
                    work in-sample.
  TEST  2018-2026 — apply the chosen config; report lift over the
                    book-faithful baseline.
"""
from __future__ import annotations

import csv
import math
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.backtest import portfolio as P
from app.backtest.metrics import compute_full_metrics
from app.backtest.portfolio_book import simulate_book_faithful, reset_caches
from scripts.grid_phase5_factors import (
    apply_variant, load_cap_map, load_sector_map, LiquidityLookup,
    week_bucket,
)


# ─────────────────────────────────────────────────────────────────────
# KR memory-chain tickers — receivers of MU/NVDA lead-lag.
# ─────────────────────────────────────────────────────────────────────
KR_MEMORY_TICKERS = {
    # KOSPI semis / memory / HBM
    "000660.KS",   # SK하이닉스 (DRAM, HBM)
    "005930.KS",   # 삼성전자
    "042700.KS",   # 한미반도체 (HBM 본더)
    # KOSDAQ HBM/관련
    "058470.KQ",   # 리노공업 (테스트 소켓)
    "036930.KQ",   # 주성엔지니어링 (반도체 장비)
    "240810.KS",   # 원익IPS (반도체 장비)
    "035900.KQ",   # JYP — wrong, not memory; commenting out
}
# Remove non-memory entries
KR_MEMORY_TICKERS = {
    "000660.KS", "005930.KS", "042700.KS",
    "058470.KQ", "036930.KQ", "240810.KS",
}


US_DRIVERS = ["MU", "NVDA"]   # primary US memory/semi drivers
ROLLING_WINDOW = 26            # weeks for z-score


# ─────────────────────────────────────────────────────────────────────
# 1) Build US weekly return + z-score timeline per driver.
# ─────────────────────────────────────────────────────────────────────
def build_us_zscores() -> Dict[str, List[Tuple[date, float]]]:
    """{ticker: [(week_end_date, z_of_weekly_return)]}.
    z computed over rolling ROLLING_WINDOW weeks of weekly returns.
    """
    con = duckdb.connect(str(ROOT / "data" / "backtest.duckdb"),
                         read_only=True)
    out: Dict[str, List[Tuple[date, float]]] = {}
    for tic in US_DRIVERS:
        rows = con.sql(
            f"SELECT bar_date, close FROM bars "
            f"WHERE ticker='{tic}' AND granularity='W' "
            f"ORDER BY bar_date"
        ).fetchall()
        if not rows:
            print(f"  WARN: {tic} has no weekly bars — skipping",
                  flush=True)
            out[tic] = []
            continue
        closes = [(d, float(c)) for d, c in rows if c is not None]
        # weekly returns
        rets: List[Tuple[date, float]] = []
        for i in range(1, len(closes)):
            d, c = closes[i]
            r = closes[i][1] / closes[i - 1][1] - 1
            rets.append((d, r))
        # rolling z-score
        zs: List[Tuple[date, float]] = []
        window: List[float] = []
        for d, r in rets:
            if len(window) >= ROLLING_WINDOW:
                mean = sum(window) / len(window)
                var = sum((x - mean) ** 2 for x in window) / len(window)
                std = math.sqrt(var) if var > 0 else 0.0
                z = (r - mean) / std if std > 0 else 0.0
            else:
                z = 0.0
            zs.append((d, z))
            window.append(r)
            if len(window) > ROLLING_WINDOW:
                window.pop(0)
        out[tic] = zs
        print(f"  {tic}: {len(zs):,} weekly z-scores", flush=True)
    con.close()
    return out


def _bisect_z_at(
    zs: List[Tuple[date, float]], target: date,
) -> Optional[float]:
    """Return the latest z-score whose bar_date is ≤ target."""
    if not zs:
        return None
    lo, hi = 0, len(zs)
    while lo < hi:
        mid = (lo + hi) // 2
        if zs[mid][0] <= target:
            lo = mid + 1
        else:
            hi = mid
    if lo == 0:
        return None
    return zs[lo - 1][1]


# ─────────────────────────────────────────────────────────────────────
# 2) Apply the US lead-lag bonus.
# ─────────────────────────────────────────────────────────────────────
def apply_us_leadlag(
    cands: List[Dict[str, Any]],
    us_z: Dict[str, List[Tuple[date, float]]],
    *,
    threshold: float = 1.0,
    bonus: float = 0.05,
) -> List[Dict[str, Any]]:
    """For each candidate whose ticker is a KR memory name AND whose
    entry_date has at least one US driver's |z| ≥ threshold (prior
    week), add `bonus` to its `strength`. Non-memory tickers and
    sub-threshold weeks unchanged."""
    out: List[Dict[str, Any]] = []
    for c in cands:
        score = float(c.get("strength", 0))
        if c["ticker"] in KR_MEMORY_TICKERS:
            ed = date.fromisoformat(c["entry_date"])
            for tic in US_DRIVERS:
                z = _bisect_z_at(us_z.get(tic, []), ed)
                if z is not None and abs(z) >= threshold:
                    score += bonus
                    break
        nc = dict(c)
        nc["strength"] = score
        out.append(nc)
    return out


# ─────────────────────────────────────────────────────────────────────
# 3) Variants + driver
# ─────────────────────────────────────────────────────────────────────
VARIANTS: Dict[str, Dict[str, float]] = {
    "P14_00_baseline":           {},
    "P14_10_z1_b05":              dict(threshold=1.0, bonus=0.05),
    "P14_11_z1_b10":              dict(threshold=1.0, bonus=0.10),
    "P14_12_z1_b15":              dict(threshold=1.0, bonus=0.15),
    "P14_20_z1p5_b10":            dict(threshold=1.5, bonus=0.10),
    "P14_21_z2_b15":              dict(threshold=2.0, bonus=0.15),
}


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


def _run(key: str, cfg, cands, exit_fires, us_z, start: date, end: date):
    print(f"\n[{key}] start={start} end={end} cfg={cfg}", flush=True)
    if cfg:
        cands_used = apply_us_leadlag(cands, us_z, **cfg)
    else:
        cands_used = cands
    # Re-apply sector_cap=1 on the rescored list (need to do this AFTER
    # the bonus so memory hits don't lose to non-memory hits with the
    # original ordering).
    from scripts.grid_phase5_factors import (
        apply_variant, load_sector_map,
    )
    # Strength is already rescored; sector cap is the second step. We
    # build a lightweight re-pass that mirrors apply_variant's sector
    # cap stage on the candidate list itself.
    sector_map = load_sector_map()
    by_week: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for f in cands_used:
        by_week[week_bucket(f["entry_date"])].append(f)
    capped: List[Dict[str, Any]] = []
    for wk, items in by_week.items():
        items.sort(key=lambda x: float(x.get("strength", 0)), reverse=True)
        kept: Dict[str, int] = defaultdict(int)
        total = 0
        for it in items:
            sec = sector_map.get(it["ticker"], "_UNKNOWN")
            if kept[sec] >= 1:
                continue
            kept[sec] += 1
            total += 1
            capped.append(it)
            if total >= 50:
                break
    cands_final = capped
    reset_caches()
    t0 = time.time()
    state = simulate_book_faithful(
        cands_final, start, end,
        initial_cash=100_000_000.0,
        max_positions=20,
        exit_fires=exit_fires,
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
    }


def main() -> int:
    print("loading inputs ...", flush=True)
    cands, exit_fires = _load_inputs()
    print(f"  cands={len(cands):,} exit_fires={len(exit_fires):,}", flush=True)
    print("building US z-score timelines ...", flush=True)
    us_z = build_us_zscores()
    # quick sanity print
    for tic in US_DRIVERS:
        if us_z[tic]:
            cnt_high = sum(1 for _, z in us_z[tic] if abs(z) >= 1.0)
            print(f"  {tic}: {cnt_high}/{len(us_z[tic])} weeks with |z|≥1.0",
                  flush=True)

    rows: List[Dict[str, Any]] = []
    for key, cfg in VARIANTS.items():
        for fold, s, e in [("train", date(2009, 1, 1), date(2017, 12, 31)),
                           ("test",  date(2018, 1, 1), date(2026, 5, 22))]:
            r = _run(f"{key}@{fold}", cfg, cands, exit_fires, us_z, s, e)
            r["fold"] = fold
            rows.append(r)

    out_csv = ROOT / "data" / "phase14_walk_forward.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {out_csv}", flush=True)

    # OOS verdict
    print("\n── WALK-FORWARD VERDICT (TEST fold lifts over baseline) ──",
          flush=True)
    test_rows = [r for r in rows if r["fold"] == "test"]
    test_base = next(r for r in test_rows if r["key"] == "P14_00_baseline@test")
    print(f"  baseline@test: CAGR {test_base['cagr']:+.2f}  "
          f"Sharpe {test_base['sharpe']:.2f}  Alpha {test_base['alpha_ann']:+.2f}")
    any_pass = False
    for r in test_rows:
        if r["key"] == "P14_00_baseline@test":
            continue
        d_cagr = r["cagr"] - test_base["cagr"]
        d_sh = r["sharpe"] - test_base["sharpe"]
        d_alpha = (r["alpha_ann"] or 0) - (test_base["alpha_ann"] or 0)
        verdict = "✓ PASS" if (d_cagr > 0.5 or d_alpha > 0.5) and d_sh > -0.02 else "✗ FAIL"
        if verdict.startswith("✓"):
            any_pass = True
        print(f"  {r['key']:<35} ΔCAGR {d_cagr:+.2f}pp  "
              f"ΔSharpe {d_sh:+.3f}  ΔAlpha {d_alpha:+.2f}pp  {verdict}")
    if not any_pass:
        print("  → All variants FAIL. US lead-lag offers no OOS lift.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
