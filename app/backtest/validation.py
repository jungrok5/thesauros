"""정직성 검증 자동화 — 모든 측정 시 표준 통과/불통과 판정.

Bootstrap p-value + Multi-seed CV + Realistic cost drag + Survivorship + OOS gap
를 한 함수로 검증.

사용:
    from app.backtest.validation import run_validated
    result = run_validated(params, panel, n_seeds=5, bootstrap_n=500)
    print(result.honesty_score)        # X / 5
    print(result.true_baseline_sharpe) # 0.X ± 0.Y
    print(result.alpha_pvalue)         # 0.0XX
    print(result.passes)               # bool — 모든 검사 통과시 True

비유:
- 실험실 표준 검증 패키지 (compliance check)
- AI 모델 평가의 cross-validation 표준화
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


@dataclass
class ValidationResult:
    """모든 측정의 표준 결과."""
    # Core
    sharpe_mean: float
    sharpe_std: float
    cagr_mean: float
    mdd_mean: float
    alpha_mean: float

    # Honesty checks
    n_seeds: int = 1
    seed_sharpes: List[float] = field(default_factory=list)
    cv: float = 0.0                    # std / |mean|
    alpha_pvalue: float = 1.0
    realistic_cost_drag: Optional[float] = None
    survivorship_drop: Optional[float] = None
    is_oos_gap: Optional[float] = None

    # Pass/fail
    pass_cv: bool = False               # CV <= 0.30
    pass_bootstrap: bool = False        # p < 0.05
    pass_cost: bool = False             # drag <= 0.15
    pass_survivorship: bool = False     # drop <= 0.20
    pass_oos: bool = False              # gap <= 0.30
    honesty_score: int = 0              # 0~5

    @property
    def passes(self) -> bool:
        """전체 통과 여부 (최소 3/5)."""
        return self.honesty_score >= 3

    @property
    def true_baseline_sharpe(self) -> str:
        """공식 보고용: 'X.XXX ± Y.YYY'"""
        return f"{self.sharpe_mean:+.3f} ± {self.sharpe_std:.3f}"

    def summary_line(self) -> str:
        cv_pct = self.cv * 100
        return (
            f"Sharpe {self.true_baseline_sharpe} (CV {cv_pct:.0f}%, "
            f"p={self.alpha_pvalue:.3f}, honesty {self.honesty_score}/5)"
        )


def _bootstrap_alpha_pvalue(returns: pd.Series, bench: pd.Series,
                              n_boot: int = 500, block: int = 20) -> float:
    """Block bootstrap p-value. Null: no alpha."""
    excess = (returns - bench).dropna()
    if len(excess) < 50:
        return 1.0
    observed = float(excess.mean() * 252)
    n = len(excess)
    n_blocks = (n + block - 1) // block
    rng = np.random.default_rng(42)
    arr = excess.values
    boot_excess = []
    for _ in range(n_boot):
        idx = rng.integers(0, n - block + 1, size=n_blocks)
        sample = np.concatenate([arr[i:i + block] for i in idx])[:n]
        boot_excess.append(float(sample.mean() * 252 - observed))
    return float((np.array(boot_excess) >= 0).mean())


def run_validated(
    run_fn,
    params_dict: Dict,
    panel: Optional[pd.DataFrame] = None,
    n_seeds: int = 5,
    bootstrap_n: int = 500,
    check_realistic_cost: bool = True,
    check_survivorship: bool = False,   # heavy; opt-in
    check_oos: bool = False,            # heavy; opt-in
    verbose: bool = True,
) -> ValidationResult:
    """Standard validated measurement.

    run_fn: callable(params) → dict with 'metrics', 'equity_curve', 'benchmark_curve'
    """
    seeds = [1, 7, 42, 100, 2026][:n_seeds]

    # ---- Multi-seed ----
    seed_results = []
    for s in seeds:
        cfg = {**params_dict, "seed": s}
        r = run_fn(cfg, panel)
        seed_results.append(r)
        if verbose:
            m = r["metrics"]
            print(f"  seed={s:>4d}: Sharpe={m['sharpe']:+.3f}, "
                  f"α={m['alpha']*100:+.2f}%")

    sharpes = [r["metrics"]["sharpe"] for r in seed_results]
    cagrs = [r["metrics"]["cagr"] for r in seed_results]
    mdds = [r["metrics"]["max_drawdown"] for r in seed_results]
    alphas = [r["metrics"]["alpha"] for r in seed_results]

    s_mean = float(np.mean(sharpes))
    s_std = float(np.std(sharpes))
    cv = abs(s_std / s_mean) if abs(s_mean) > 1e-6 else 999.0

    # ---- Bootstrap (use first seed run) ----
    first = seed_results[0]
    eq = first.get("equity_curve")
    bench = first.get("benchmark_curve")
    p_value = 1.0
    if eq is not None and bench is not None:
        rets = eq.pct_change().dropna()
        bench_rets = bench.pct_change().dropna()
        p_value = _bootstrap_alpha_pvalue(rets, bench_rets, n_boot=bootstrap_n)

    # ---- Realistic cost ----
    cost_drag = None
    if check_realistic_cost:
        cfg_real = {**params_dict, "seed": seeds[0], "realistic_costs": True}
        r_real = run_fn(cfg_real, panel)
        cost_drag = first["metrics"]["sharpe"] - r_real["metrics"]["sharpe"]
        if verbose:
            print(f"  Realistic-cost drag: {cost_drag:+.3f}")

    # ---- Survivorship ----
    surv_drop = None
    if check_survivorship:
        cfg_surv = {**params_dict, "seed": seeds[0],
                    "use_survivorship_correction": True}
        r_surv = run_fn(cfg_surv, panel)
        surv_drop = first["metrics"]["sharpe"] - r_surv["metrics"]["sharpe"]
        if verbose:
            print(f"  Survivorship drop: {surv_drop:+.3f}")

    # ---- OOS gap ----
    oos_gap = None
    if check_oos:
        cfg_is = {**params_dict, "seed": seeds[0],
                  "start": "2015-01-01", "end": "2018-12-31"}
        cfg_oos = {**params_dict, "seed": seeds[0],
                    "start": "2019-01-01", "end": "2024-12-31"}
        r_is = run_fn(cfg_is, panel)
        r_oos = run_fn(cfg_oos, panel)
        oos_gap = r_is["metrics"]["sharpe"] - r_oos["metrics"]["sharpe"]
        if verbose:
            print(f"  IS-OOS gap: {oos_gap:+.3f}")

    # ---- Honesty score ----
    pass_cv = cv <= 0.30
    pass_boot = p_value < 0.05
    pass_cost = cost_drag is None or cost_drag <= 0.15
    pass_surv = surv_drop is None or abs(surv_drop) <= 0.20
    pass_oos = oos_gap is None or abs(oos_gap) <= 0.30
    score = sum([pass_cv, pass_boot, pass_cost, pass_surv, pass_oos])

    return ValidationResult(
        sharpe_mean=s_mean, sharpe_std=s_std,
        cagr_mean=float(np.mean(cagrs)),
        mdd_mean=float(np.mean(mdds)),
        alpha_mean=float(np.mean(alphas)),
        n_seeds=n_seeds, seed_sharpes=sharpes, cv=cv,
        alpha_pvalue=p_value,
        realistic_cost_drag=cost_drag,
        survivorship_drop=surv_drop,
        is_oos_gap=oos_gap,
        pass_cv=pass_cv, pass_bootstrap=pass_boot, pass_cost=pass_cost,
        pass_survivorship=pass_surv, pass_oos=pass_oos,
        honesty_score=score,
    )


# Convenience: wrap run_wf_v3 for validation
def wf_runner(params_dict: Dict, panel) -> Dict:
    from app.backtest.walkforward_v3 import WFv3Params, run_wf_v3
    return run_wf_v3(WFv3Params(**params_dict), panel=panel.copy(), verbose=False)


# ---------------------------------------------------------------------------
# Sub-period decomposition — 통합 백테스트 결과를 시기별로 자동 분해
# ---------------------------------------------------------------------------
# KR 시장 주요 국면 (2008-2024)
KR_SUBPERIODS = [
    ("2008 금융위기", "2008-01-01", "2009-12-31"),
    ("2010-11 회복", "2010-01-01", "2011-12-31"),
    ("2012-16 박스피", "2012-01-01", "2016-12-31"),
    ("2017-19 대형주 장세", "2017-01-01", "2019-12-31"),
    ("2020-21 코로나 V자", "2020-01-01", "2021-12-31"),
    ("2022 금리인상 하락", "2022-01-01", "2022-12-31"),
    ("2023-24 회복", "2023-01-01", "2024-12-31"),
]

# US 시장 주요 국면
US_SUBPERIODS = [
    ("2008 금융위기", "2008-01-01", "2009-12-31"),
    ("2010-15 회복", "2010-01-01", "2015-12-31"),
    ("2016-19 강세", "2016-01-01", "2019-12-31"),
    ("2020 코로나", "2020-01-01", "2020-12-31"),
    ("2021 회복+버블", "2021-01-01", "2021-12-31"),
    ("2022 약세장", "2022-01-01", "2022-12-31"),
    ("2023-24 AI 강세", "2023-01-01", "2024-12-31"),
]


def decompose_by_period(eq: pd.Series, bench: pd.Series,
                          periods: List[tuple]) -> List[Dict]:
    """Equity curve 를 시기별로 분해해서 각 구간 metrics 계산.

    Args:
        eq: pd.Series of strategy equity (datetime index)
        bench: pd.Series of benchmark equity
        periods: [(label, start, end), ...]
    Returns:
        List of dicts: [{label, start, end, sharpe, cagr, mdd, alpha, n_days}, ...]
    """
    eq.index = pd.to_datetime(eq.index)
    bench.index = pd.to_datetime(bench.index)
    out = []
    for label, start, end in periods:
        mask = (eq.index >= pd.Timestamp(start)) & (eq.index <= pd.Timestamp(end))
        eq_p = eq.loc[mask]
        bench_p = bench.loc[mask]
        if len(eq_p) < 20:
            out.append({"label": label, "start": start, "end": end,
                         "n_days": 0, "skipped": True})
            continue
        # Normalize to start at 1.0
        eq_p = eq_p / eq_p.iloc[0]
        bench_p = bench_p / bench_p.iloc[0]
        days = (eq_p.index[-1] - eq_p.index[0]).days
        years = max(days / 365.25, 1e-6)
        total = float(eq_p.iloc[-1] - 1)
        bench_total = float(bench_p.iloc[-1] - 1)
        cagr = float(eq_p.iloc[-1] ** (1 / years) - 1) if eq_p.iloc[-1] > 0 else -1
        bench_cagr = float(bench_p.iloc[-1] ** (1 / years) - 1) if bench_p.iloc[-1] > 0 else -1
        rets = eq_p.pct_change().dropna()
        vol = float(rets.std() * np.sqrt(252)) if len(rets) > 1 else 0
        sharpe = float(cagr / vol) if vol > 0 else 0
        mdd = float((eq_p / eq_p.cummax() - 1).min())
        out.append({
            "label": label, "start": start, "end": end,
            "n_days": int(len(eq_p)),
            "total_return": total,
            "bench_total_return": bench_total,
            "alpha": total - bench_total,
            "cagr": cagr,
            "bench_cagr": bench_cagr,
            "alpha_cagr": cagr - bench_cagr,
            "sharpe": sharpe,
            "mdd": mdd,
            "vol_annual": vol,
        })
    return out


def format_subperiod_table(rows: List[Dict]) -> str:
    """Pretty-print sub-period decomposition table."""
    lines = []
    lines.append(f"  {'Period':<22s} {'Days':>5s} {'Sharpe':>8s} "
                  f"{'CAGR':>8s} {'B&H':>8s} {'α':>8s} {'MDD':>8s}")
    lines.append("  " + "-" * 74)
    for r in rows:
        if r.get("skipped"):
            lines.append(f"  {r['label']:<22s} (data insufficient)")
            continue
        lines.append(
            f"  {r['label']:<22s} {r['n_days']:>5d} "
            f"{r['sharpe']:>+8.3f} {r['cagr']*100:>+7.2f}% "
            f"{r['bench_cagr']*100:>+7.2f}% {r['alpha_cagr']*100:>+7.2f}% "
            f"{r['mdd']*100:>+7.2f}%"
        )
    return "\n".join(lines)
