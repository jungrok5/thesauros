"""Phase 4-0: KR + 2008-2024 + survivorship 보정 + Gemini 필터.

지인 시스템 (Sharpe 1.2) 와 직접 비교 가능한 진짜 baseline.

조건 (지인과 동일):
  - KR only (코스피 + 코스닥)
  - 2008-2024 (16년)
  - 상폐 종목 포함 + survivorship correction
  - 우선주/스팩/금융/지주 제외 (Gemini 가이드)

최종 시스템 적용:
  - Multi-factor 5-group (V/Q/M/L/Book = 25/25/15/15/20) — Phase 5a best
  - + 책 V4 EXIT overlay (0.85)
  - + LS 100/30 mild hedge — Phase 3d best
  - + Deterministic (multi_factor only)

비교 측정:
  1. 통합 16년 (2008-2024) Sharpe / CAGR / MDD
  2. Sub-period 분해 (2008위기 / 박스피 / 2017-19 / 2020 코로나 / 2022 / 2023-24)
  3. Bootstrap p-value
  4. Realistic cost (KR 0.18% + 50bp)
"""
from __future__ import annotations

import json, math, sys, time, warnings
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

warnings.filterwarnings("ignore")

import numpy as np

from app.backtest.walkforward_v3 import WFv3Params, run_wf_v3
from app.features.pipeline_v3 import build_panel_v3
from app.backtest.validation import (
    _bootstrap_alpha_pvalue, decompose_by_period,
    format_subperiod_table, KR_SUBPERIODS,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DOCS_DIR = Path("docs/optimization")


def fpct(x): return f"{x*100:+.2f}%" if x is not None and not math.isnan(x) else "—"
def fnum(x): return f"{x:+.3f}" if x is not None and not math.isnan(x) else "—"


def main() -> int:
    log_path = DOCS_DIR / "phase_4_0_kr_run_log.txt"
    log = open(log_path, "w", encoding="utf-8")
    def L(msg):
        print(msg, flush=True); log.write(msg + "\n"); log.flush()

    L("=== Phase 4-0: KR canonical (지인 조건 매칭) ===")
    L(f"Start: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    L("\nUniverse: KR (.KS + .KQ), 2008-2024, survivorship corrected, filtered")

    # ---- 1. Sanity: KR signal cache 확인 ----
    L("\n--- Sanity: KR signal cache check ---")
    from app.cache.signal_cache import DEFAULT_CACHE_DIR
    weekly_dir = DEFAULT_CACHE_DIR / "weekly"
    kr_caches = list(weekly_dir.glob("*.KS.parquet")) + list(weekly_dir.glob("*.KQ.parquet"))
    L(f"  KR cached tickers: {len(kr_caches) // 2}")  # signals + bars
    if len(kr_caches) < 200:
        L(f"  ⚠️ KR cache too small. ABORT — KR cache build first.")
        return 1

    # ---- 2. Panel build (KR, 2008-2024) ----
    L("\n--- Panel build (KR universe, 2008-2024) ---")
    t0 = time.time()
    try:
        panel = build_panel_v3(
            start="2008-01-01", end="2024-12-31",
            rebalance_n=21, with_target=True,
            sector_neutralize=True,
            with_book_features=True,
            market="kr",                    # KR only
            verbose=False,
        )
        L(f"  Panel: {panel.shape} in {time.time()-t0:.0f}s")
    except Exception as e:
        L(f"  ERR: {e}")
        import traceback; traceback.print_exc(file=log)
        return 1

    # ---- 3. Phase 5a winner params, applied to KR ----
    base = dict(
        start="2010-01-01", end="2024-12-31",     # 2008-2009 warmup
        train_start="2008-01-01",
        rebalance_n=21, top_k=20,
        cost_bps=18, slippage_bps=50,              # KR 거래세 + slippage
        sector_cap=0.25, drawdown_brake=-0.15,
        use_rank_target=True, feature_suffix="_sn",
        market="kr",
        use_multifactor_only=True,
        mf_weights={
            "value": 0.25, "quality": 0.25,
            "momentum": 0.15, "lowvol": 0.15,
            "book": 0.20,
        },
        use_book_features=True,
        book_exit_overlay=True, book_exit_min_conf=0.85,
        enable_short=False,                         # KR 공매도 제한 多. long-only 먼저
        use_survivorship_correction=True,           # 강제
        use_kr_filter=True,                         # Gemini 필터 ON
        kr_min_daily_value_krw=100_000_000,         # 1억
    )

    L("\n--- Phase 4-0 measurement (KR canonical) ---")
    L(f"  Universe filter: 우선주/스팩/금융/지주 제외 + 거래대금 ≥1억")
    L(f"  Survivorship correction: ON (universe_alive_at)")
    L(f"  MF weights: {base['mf_weights']}")
    t0 = time.time()
    res = run_wf_v3(WFv3Params(**base), panel=panel.copy(), verbose=False)
    m = res["metrics"]
    n_forced = res.get("n_forced_exits", 0)
    L(f"  Sharpe={fnum(m['sharpe'])}, α={fpct(m['alpha'])}, "
      f"MDD={fpct(m['max_drawdown'])}, CAGR={fpct(m['cagr'])}, "
      f"vol={fpct(m['vol_annual'])}, forced={n_forced}, "
      f"{time.time()-t0:.0f}s")

    # ---- 4. Bootstrap ----
    L(f"\n--- Bootstrap p-value (1000 iterations) ---")
    eq = res["equity_curve"]; bench = res["benchmark_curve"]
    rets = eq.pct_change().dropna()
    bench_rets = bench.pct_change().dropna()
    p_value = _bootstrap_alpha_pvalue(rets, bench_rets, n_boot=1000, block=20)
    L(f"  p-value = {p_value:.4f}  {'<0.05 PASS' if p_value < 0.05 else 'NOT significant'}")

    # ---- 5. Sub-period decomposition ----
    L(f"\n--- Sub-period decomposition (KR major regimes) ---")
    sub = decompose_by_period(eq, bench, KR_SUBPERIODS)
    L(format_subperiod_table(sub))

    # ---- 6. Realistic cost (already KR cost in base) ----
    L(f"\n--- Realistic cost check (base cost 0.68%) ---")
    t0 = time.time()
    res_naive = run_wf_v3(
        WFv3Params(**{**base, "cost_bps": 5, "slippage_bps": 5}),
        panel=panel.copy(), verbose=False,
    )
    m_naive = res_naive["metrics"]
    drag = m_naive['sharpe'] - m['sharpe']
    L(f"  Naive cost (10bp) Sharpe: {fnum(m_naive['sharpe'])}")
    L(f"  Realistic cost (68bp) Sharpe: {fnum(m['sharpe'])}")
    L(f"  Drag: {drag:+.3f}")

    # ---- 7. 지인 비교 ----
    L(f"\n{'='*72}")
    L(f"  PHASE 4-0 — KR CANONICAL (지인 조건 매칭)")
    L(f"{'='*72}")
    L(f"  지인 (보고)             Sharpe ~1.20")
    L(f"  우리 (KR canonical)     Sharpe {fnum(m['sharpe'])}")
    L(f"  Gap                     {1.20 - m['sharpe']:+.3f}")
    L(f"\n  Bootstrap p-value: {p_value:.4f}")
    L(f"  Realistic cost: 적용됨 (KR 0.18% + 50bp slippage)")
    L(f"  Survivorship: 보정됨")
    L(f"  Filter: 우선주/스팩/금융/지주 제외")

    def clean(o):
        if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list): return [clean(x) for x in o]
        if isinstance(o, float):
            return None if (math.isnan(o) or math.isinf(o)) else o
        if isinstance(o, (np.integer, np.floating, np.bool_)):
            return o.item()
        return o

    out = {
        "phase": "4-0",
        "config": base,
        "metrics": clean(m),
        "naive_cost_metrics": clean(m_naive),
        "cost_drag": float(drag),
        "bootstrap_pvalue": p_value,
        "sub_periods": clean(sub),
        "n_forced_exits": n_forced,
        "friend_gap": float(1.20 - m['sharpe']),
    }
    with open(DOCS_DIR / "phase_4_0_kr_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    L(f"\nSaved {DOCS_DIR}/phase_4_0_kr_results.json")
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
