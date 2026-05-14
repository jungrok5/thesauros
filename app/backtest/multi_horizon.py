"""Multi-horizon ensemble (P5).

Trains three LightGBM models on different forward-return horizons
(5d short-term reversal, 21d core, 63d trend) and blends their
predictions for a more stable ranking score.

Why this helps:
  - 21d alone has notoriously high noise (single-month IC moves ±0.05 easily)
  - Different horizons capture different alpha regimes
  - Bagged-by-horizon ensembles typically lift Sharpe 0.05-0.15

Usage:
    from app.backtest.multi_horizon import train_ensemble, predict_ensemble
    bundle = train_ensemble(panel, feature_cols)
    scores = predict_ensemble(test_panel, bundle)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr


HORIZONS = [5, 21, 63]

# Weight per horizon — favors 21d (default modeling horizon).
DEFAULT_HORIZON_WEIGHTS = {5: 0.20, 21: 0.55, 63: 0.25}


def _default_params() -> Dict:
    return {
        "objective": "regression",
        "metric": "rmse",
        "learning_rate": 0.05,
        "num_leaves": 63,
        "min_data_in_leaf": 100,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "lambda_l2": 1.0,
        "verbose": -1,
    }


@dataclass
class EnsembleBundle:
    models: Dict[int, "lgb.Booster"] = field(default_factory=dict)
    feature_cols: List[str] = field(default_factory=list)
    horizon_weights: Dict[int, float] = field(
        default_factory=lambda: dict(DEFAULT_HORIZON_WEIGHTS),
    )
    fold_ics: Dict[int, float] = field(default_factory=dict)


def _target_col_for(horizon: int) -> str:
    """Column name produced by pipeline_v3 for a given horizon."""
    if horizon == 21:
        return "y_rank"
    return f"y_rank_{horizon}d"


def train_ensemble(panel: pd.DataFrame, feature_cols: List[str],
                   horizons: List[int] = None,
                   params: Optional[Dict] = None,
                   boost_rounds: int = 300,
                   verbose: bool = True) -> EnsembleBundle:
    """Train one LightGBM model per horizon.

    Panel must have columns y_rank, y_rank_5d, y_rank_63d (or fallback raw).
    """
    horizons = horizons or HORIZONS
    p = params or _default_params()

    bundle = EnsembleBundle(feature_cols=feature_cols)
    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"])

    for h in horizons:
        col = _target_col_for(h)
        if col not in panel.columns:
            if verbose:
                print(f"  [ensemble] missing target {col} → skip {h}d horizon")
            continue
        train = panel.dropna(subset=[col]).copy()
        if len(train) < 5000:
            if verbose:
                print(f"  [ensemble] {h}d: not enough rows ({len(train)})")
            continue
        X = train[feature_cols]
        y = train[col].astype(float)

        # Quick OOF IC via 5-fold purged CV would be ideal here, but we
        # train on the full panel and just report in-sample fit. Caller
        # is expected to use walk-forward for OOS evaluation.
        model = lgb.train(p, lgb.Dataset(X, label=y),
                          num_boost_round=boost_rounds)
        bundle.models[h] = model

        # In-sample IC as a sanity check
        pred = model.predict(X)
        ic = float(spearmanr(pred, y)[0]) if len(y) > 5 else 0.0
        bundle.fold_ics[h] = ic
        if verbose:
            print(f"  [ensemble] horizon={h}d trained "
                  f"(IS IC={ic:+.4f}, n={len(y)})")

    # Re-normalize weights to the trained horizons only.
    total = sum(bundle.horizon_weights.get(h, 0) for h in bundle.models)
    if total > 0:
        bundle.horizon_weights = {
            h: bundle.horizon_weights.get(h, 0) / total
            for h in bundle.models
        }
    else:
        # equal weight fallback
        n = max(len(bundle.models), 1)
        bundle.horizon_weights = {h: 1.0 / n for h in bundle.models}
    return bundle


def predict_ensemble(panel: pd.DataFrame, bundle: EnsembleBundle) -> pd.Series:
    """Blend per-horizon predictions with the configured weights."""
    if not bundle.models:
        return pd.Series(np.nan, index=panel.index)
    X = panel[bundle.feature_cols]

    # Get rank-percentile predictions per horizon, then weighted average.
    blended = pd.Series(0.0, index=panel.index)
    for h, model in bundle.models.items():
        raw = pd.Series(model.predict(X), index=panel.index)
        # Cross-sectional percentile per date so horizons are comparable.
        if "date" in panel.columns:
            ranks = (
                pd.DataFrame({"d": panel["date"].values, "p": raw.values},
                             index=panel.index)
                .groupby("d")["p"]
                .rank(pct=True, method="average")
            )
        else:
            ranks = raw.rank(pct=True, method="average")
        blended += bundle.horizon_weights[h] * ranks
    return blended
