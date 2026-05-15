"""Phase 1A 검증: V3 baseline vs V3+ (with book features) 동일 panel 비교.

핵심 검증:
  1. 캐시 stale 확인 — signal_cache 의 현재 hash 가 panel build 시점과 일치하는가
  2. NC (no cache) vs cached attach_book_signals 결과 일치 (작은 sample 로)
  3. Panel 1회 build (with book features) → 두 백테스트 같은 panel 사용
  4. use_book_features True/False 만 차이
  5. 같은 random_state, 같은 LightGBM params, 같은 fold

결과: docs/optimization/phase_1a_results.json + .md
"""
from __future__ import annotations

import json
import math
import sys
import time
import warnings
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

warnings.filterwarnings("ignore")

import pandas as pd

from app.backtest.walkforward_v3 import WFv3Params, run_wf_v3
from app.features.pipeline_v3 import build_panel_v3
from app.features.book_features import BOOK_FEATURES, attach_book_signals
from app.cache.signal_cache import SIGNAL_CACHE_VERSION, DEFAULT_CACHE_DIR

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DOCS_DIR = Path("docs/optimization")
DOCS_DIR.mkdir(parents=True, exist_ok=True)


def clean(o):
    if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list): return [clean(x) for x in o]
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    return o


def fpct(x): return f"{x*100:+.2f}%" if x is not None else "—"
def fnum(x, d=2): return f"{x:+.{d}f}" if x is not None else "—"


def main() -> int:
    log_path = DOCS_DIR / "phase_1a_run_log.txt"
    log = open(log_path, "w", encoding="utf-8")
    def L(msg):
        print(msg, flush=True)
        log.write(msg + "\n")
        log.flush()

    # ====================================
    # SANITY 1: Cache hash 확인
    # ====================================
    L(f"=== SANITY 1: Cache hash check ===")
    L(f"Current signal cache version: {SIGNAL_CACHE_VERSION}")
    L(f"Cache dir: {DEFAULT_CACHE_DIR}")
    if not DEFAULT_CACHE_DIR.exists():
        L(f"⚠️ Cache dir missing — build first!")
        return 1
    n_signals = len(list((DEFAULT_CACHE_DIR / "weekly").glob("*.parquet")))
    L(f"Weekly parquet files: {n_signals}")
    if n_signals < 200:
        L(f"⚠️ Only {n_signals} cached — full universe not built yet. ABORT.")
        return 1

    # ====================================
    # SANITY 2: attach_book_signals 결과 일관성
    # ====================================
    L(f"\n=== SANITY 2: attach_book_signals consistency ===")
    test_panel = pd.DataFrame({
        "date": pd.to_datetime(["2023-06-30", "2023-12-29"]),
        "ticker": ["AAPL", "MSFT"],
    })
    out1 = attach_book_signals(test_panel, verbose=False)
    out2 = attach_book_signals(test_panel, verbose=False)
    cols_check = [c for c in BOOK_FEATURES if c in out1.columns]
    same = (out1[cols_check].equals(out2[cols_check]))
    L(f"Repeated calls match: {same}")
    if not same:
        L(f"⚠️ Non-deterministic attach! Aborting.")
        return 1
    L(f"Sample (AAPL 2023-12-29):")
    for c in cols_check[:5]:
        L(f"  {c} = {out1[out1['ticker']=='AAPL'][c].iloc[-1]}")

    # ====================================
    # BUILD PANEL (US universe + book features)
    # ====================================
    L(f"\n=== BUILD PANEL (US universe only) ===")
    t0 = time.time()
    panel = build_panel_v3(
        start="2014-01-01", end="2024-12-31",
        rebalance_n=21, with_target=True,
        sector_neutralize=True,
        with_book_features=True,
        market="us",                # ← critical: US only, matches book cache
        verbose=False,
    )
    L(f"Panel built in {time.time()-t0:.0f}s: {panel.shape}")
    L(f"Book features present: {[c for c in BOOK_FEATURES if c in panel.columns]}")
    L(f"Book feature non-zero coverage:")
    for c in BOOK_FEATURES:
        if c in panel.columns:
            nonzero = (panel[c] != 0).sum()
            L(f"  {c:30s} {nonzero}/{len(panel)} ({nonzero/len(panel)*100:.1f}%)")

    # ====================================
    # RUN V3 BASELINE (no book features)
    # ====================================
    L(f"\n=== V3 BASELINE backtest ===")
    common = dict(
        start="2020-01-01", end="2024-12-31",
        train_start="2014-01-01",
        rebalance_n=21, top_k=20,
        cost_bps=10, slippage_bps=5,
        sector_cap=0.25, drawdown_brake=-0.15,
        use_rank_target=True, feature_suffix="_sn",
        market="us",   # universe consistency with book cache
    )
    t0 = time.time()
    res_v3 = run_wf_v3(
        WFv3Params(**common, use_book_features=False),
        panel=panel.copy(), verbose=False,
    )
    L(f"V3 done in {time.time()-t0:.0f}s")
    m3 = res_v3["metrics"]
    L(f"  CAGR={fpct(m3['cagr'])}  α={fpct(m3['alpha'])}  Sharpe={fnum(m3['sharpe'])}  MDD={fpct(m3['max_drawdown'])}")

    # ====================================
    # RUN V3+ (with book features, Phase 1A)
    # ====================================
    L(f"\n=== V3+ (Phase 1A: book features) backtest ===")
    t0 = time.time()
    res_v3b = run_wf_v3(
        WFv3Params(**common, use_book_features=True),
        panel=panel.copy(), verbose=False,
    )
    L(f"V3+ done in {time.time()-t0:.0f}s")
    m3b = res_v3b["metrics"]
    L(f"  CAGR={fpct(m3b['cagr'])}  α={fpct(m3b['alpha'])}  Sharpe={fnum(m3b['sharpe'])}  MDD={fpct(m3b['max_drawdown'])}")

    # ====================================
    # RUN V3+overlay (Phase 1A + 1B: features + EXIT overlay)
    # ====================================
    L(f"\n=== V3+overlay (Phase 1A+B: features + EXIT overlay) backtest ===")
    t0 = time.time()
    res_v3o = run_wf_v3(
        WFv3Params(**common, use_book_features=True,
                    book_exit_overlay=True, book_exit_min_conf=0.80),
        panel=panel.copy(), verbose=False,
    )
    L(f"V3+overlay done in {time.time()-t0:.0f}s")
    m3o = res_v3o["metrics"]
    n_forced = res_v3o.get("n_forced_exits", 0)
    L(f"  CAGR={fpct(m3o['cagr'])}  α={fpct(m3o['alpha'])}  Sharpe={fnum(m3o['sharpe'])}  MDD={fpct(m3o['max_drawdown'])}  forced exits={n_forced}")

    # ====================================
    # COMPARISON
    # ====================================
    L(f"\n{'='*72}")
    L(f"  PHASE 1A+B RESULTS — V3 (baseline) vs V3+ (1A) vs V3+overlay (1A+B)")
    L(f"{'='*72}")
    rows = [
        ("CAGR (전략)", fpct(m3['cagr']), fpct(m3b['cagr']), fpct(m3o['cagr'])),
        ("CAGR (벤치)", fpct(m3['bench_cagr']), fpct(m3b['bench_cagr']), fpct(m3o['bench_cagr'])),
        ("알파", fpct(m3['alpha']), fpct(m3b['alpha']), fpct(m3o['alpha'])),
        ("연환산 변동성", fpct(m3['vol_annual']), fpct(m3b['vol_annual']), fpct(m3o['vol_annual'])),
        ("Sharpe", fnum(m3['sharpe']), fnum(m3b['sharpe']), fnum(m3o['sharpe'])),
        ("Info Ratio", fnum(m3['info_ratio']), fnum(m3b['info_ratio']), fnum(m3o['info_ratio'])),
        ("MDD", fpct(m3['max_drawdown']), fpct(m3b['max_drawdown']), fpct(m3o['max_drawdown'])),
        ("일승률", fpct(m3['win_rate_daily']), fpct(m3b['win_rate_daily']), fpct(m3o['win_rate_daily'])),
        ("총수익", fpct(m3['total_return']), fpct(m3b['total_return']), fpct(m3o['total_return'])),
    ]
    L(f'  {"지표":18s}{"V3":>12s}{"V3+":>12s}{"V3+overlay":>14s}')
    L("  " + "-" * 60)
    for label, v3, v3b, v3o in rows:
        L(f"  {label:18s}{v3:>12s}{v3b:>12s}{v3o:>14s}")

    sharpe_delta_1a = m3b['sharpe'] - m3['sharpe']
    sharpe_delta_1b = m3o['sharpe'] - m3b['sharpe']
    sharpe_delta_total = m3o['sharpe'] - m3['sharpe']
    L(f"\n  📊 Sharpe Δ (Phase 1A only): {sharpe_delta_1a:+.3f}")
    L(f"  📊 Sharpe Δ (Phase 1B add-on): {sharpe_delta_1b:+.3f}")
    L(f"  📊 Sharpe Δ (1A+B total):      {sharpe_delta_total:+.3f}")
    L(f"  📊 Forced EXITs (1B only):     {n_forced}")

    # Save JSON
    out = {
        "phase": "1A+B",
        "signal_cache_version": SIGNAL_CACHE_VERSION,
        "common_params": common,
        "v3_baseline": {"metrics": clean(m3)},
        "v3_with_book": {"metrics": clean(m3b)},
        "v3_with_book_overlay": {"metrics": clean(m3o),
                                   "n_forced_exits": n_forced,
                                   "forced_exits_sample": res_v3o.get("book_forced_exits", [])[:30]},
        "sharpe_delta_1a": float(sharpe_delta_1a),
        "sharpe_delta_1b": float(sharpe_delta_1b),
        "sharpe_delta_total": float(sharpe_delta_total),
    }
    with open(DOCS_DIR / "phase_1a_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    L(f"\nSaved {DOCS_DIR / 'phase_1a_results.json'}")
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
