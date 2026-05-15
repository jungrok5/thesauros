"""Multi-factor deterministic scorer — Phase 3b.

학계 multi-factor model (Fama-French, AQR Style Premia) 의 한국 시장
적용판. 강환국식 4-factor (Value + Quality + Momentum + Low-Vol) +
Alpha158 (Microsoft Qlib) 의 좋은 부분 일부.

100% deterministic: 같은 input → 항상 같은 output. 운에 의존 X.
LightGBM 학습 비용 0. capacity 큼 (큰 자금 가능).

비교 시나리오:
  - multifactor_only: ML 없이 score 만 사용 → top-K 선정
  - hybrid: multifactor + LightGBM 의 평균 (또는 LightGBM 이 multifactor
    score 를 feature 로 받아 학습)

Style:
  - Cross-sectional rank per date (대형주/소형주 비교 안 함)
  - Z-score sector-neutralized 옵션
  - Combined score = weighted sum of factor ranks
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Factor groups (using existing ALL_V3 columns from pipeline_v3)
# ---------------------------------------------------------------------------
#
# Each factor: name → (panel column, direction).
# direction +1 = "higher is better", -1 = "lower is better".

VALUE_FACTORS = {
    "earnings_yield": +1,    # 1/PE (already inverted)
    "fcf_yield": +1,         # FCF/MarketCap
    "value_composite": +1,   # composite of PE/PB/PS
    "pe": -1,                # lower = cheaper
    "pb": -1,
    "ps": -1,
}

QUALITY_FACTORS = {
    "roe_ttm": +1,
    "roa_ttm": +1,
    "op_margin": +1,
    "gross_margin": +1,
    "asness_quality": +1,
    "piotroski_f": +1,
    "current_ratio": +1,
    "debt_to_equity": -1,    # less leverage
    "leverage": -1,
    "liab_to_assets": -1,
    "beneish_m": -1,         # higher M = earnings manipulation
}

MOMENTUM_FACTORS = {
    "mom_12_1": +1,          # 12-month minus most recent 1 month (academic standard)
    "mom_3m": +1,            # short-term
    "mom_6m": +1,
    "consistency_12m": +1,
    "macd_hist": +1,
}

LOWVOL_FACTORS = {
    "vol_60": -1,            # lower vol = better
    "vol_20": -1,
    "dd_252": +1,            # less negative drawdown = higher (closer to 0)
}

# Default weights (강환국식 + AQR Style Premia approximation)
DEFAULT_WEIGHTS = {
    "value": 0.30,
    "quality": 0.30,
    "momentum": 0.20,
    "lowvol": 0.20,
}


@dataclass
class MultiFactorParams:
    weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    sector_neutralize: bool = True
    winsorize_pct: float = 0.01    # 1%/99% clip per date (outlier robustness)


def _rank_pct(s: pd.Series) -> pd.Series:
    """Cross-sectional rank in [0, 1]. NaN-safe."""
    return s.rank(pct=True, method="average")


def _winsorize(s: pd.Series, p: float) -> pd.Series:
    if p <= 0:
        return s
    lo = s.quantile(p)
    hi = s.quantile(1 - p)
    return s.clip(lower=lo, upper=hi)


def _factor_group_score(panel_date: pd.DataFrame, factors: Dict[str, int],
                         winsorize_pct: float = 0.01) -> pd.Series:
    """For one date's panel, compute weighted-rank score for a factor group.

    Each factor: rank → average across factors in the group.
    Direction +1 = higher better; -1 = invert.
    Missing factors are dropped.
    """
    ranks = []
    for col, direction in factors.items():
        if col not in panel_date.columns:
            continue
        s = panel_date[col]
        if s.isna().all():
            continue
        s = _winsorize(s, winsorize_pct)
        r = _rank_pct(s)
        if direction == -1:
            r = 1 - r
        ranks.append(r)
    if not ranks:
        return pd.Series(0.5, index=panel_date.index)  # neutral if no data
    return pd.concat(ranks, axis=1).mean(axis=1)


def compute_multifactor_score(panel: pd.DataFrame,
                                params: Optional[MultiFactorParams] = None,
                                verbose: bool = False) -> pd.Series:
    """Deterministic multi-factor score for the entire panel.

    Returns pd.Series indexed by panel.index. Higher = better.
    """
    p = params or MultiFactorParams()
    if "date" not in panel.columns or "ticker" not in panel.columns:
        raise ValueError("panel must have 'date' and 'ticker' columns")

    if verbose:
        print(f"[multifactor] panel {panel.shape}, weights={p.weights}")

    groups = {
        "value": VALUE_FACTORS,
        "quality": QUALITY_FACTORS,
        "momentum": MOMENTUM_FACTORS,
        "lowvol": LOWVOL_FACTORS,
    }

    # For each factor group, build a Series indexed like panel
    group_scores: Dict[str, pd.Series] = {}
    for grp_name, factors in groups.items():
        w = p.weights.get(grp_name, 0.0)
        if w <= 0:
            continue
        # Average of per-factor ranks (within date)
        per_factor_ranks: List[pd.Series] = []
        for col, direction in factors.items():
            if col not in panel.columns:
                continue
            raw = panel[col]
            if raw.isna().all():
                continue
            # Cross-sectional rank within each date
            r = panel.groupby("date")[col].transform(
                lambda x: _winsorize(x, p.winsorize_pct).rank(pct=True, method="average")
            )
            if direction == -1:
                r = 1 - r
            per_factor_ranks.append(r)
        if not per_factor_ranks:
            group_scores[grp_name] = pd.Series(0.5, index=panel.index)
            continue
        # Average rank across factors in this group
        df_g = pd.concat(per_factor_ranks, axis=1)
        group_scores[grp_name] = df_g.mean(axis=1)
        if verbose:
            mean_v = float(group_scores[grp_name].mean())
            n_used = len(per_factor_ranks)
            print(f"  [{grp_name}] weight={w:.2f}, n_factors={n_used}, mean={mean_v:.3f}")

    # Weighted combination
    combined = pd.Series(0.0, index=panel.index)
    for grp_name, score in group_scores.items():
        combined = combined.add(score * p.weights.get(grp_name, 0.0), fill_value=0)

    # Sector neutralization
    if p.sector_neutralize and "sector" in panel.columns:
        df = panel[["date", "sector"]].copy()
        df["score"] = combined
        sector_mean = df.groupby(["date", "sector"])["score"].transform("mean")
        combined = combined - sector_mean

    return combined


def select_topk_multifactor(panel: pd.DataFrame, k: int = 20,
                              params: Optional[MultiFactorParams] = None) -> pd.DataFrame:
    """For each date, return top-K tickers by multi-factor score."""
    panel = panel.copy()
    panel["mf_score"] = compute_multifactor_score(panel, params)
    top = (
        panel.groupby("date")
             .apply(lambda d: d.nlargest(k, "mf_score"), include_groups=False)
             .reset_index(level=0)
    )
    return top


# ---------------------------------------------------------------------------
# Quick sanity-test utility
# ---------------------------------------------------------------------------
def smoke_test(panel: pd.DataFrame, verbose: bool = True) -> Dict:
    """Run scorer on a panel, return summary statistics."""
    s = compute_multifactor_score(panel, verbose=verbose)
    return {
        "n_rows": len(s),
        "n_nonzero": int((s > 0).sum()),
        "mean": float(s.mean()),
        "std": float(s.std()),
        "min": float(s.min()),
        "max": float(s.max()),
        "n_dates": panel["date"].nunique(),
        "n_tickers": panel["ticker"].nunique(),
    }
