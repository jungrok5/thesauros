"""Train a LightGBM ranker / regressor with PurgedKFold + Embargo CV.

Default task: predict the 21-day forward return (regression). We use the
prediction as a cross-sectional score for ranking the top-K stocks.

The "validation" each fold is the OOS Spearman rank-IC vs target — the
standard metric for cross-sectional alpha models.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from app.config import EMBARGO_DAYS, FORWARD_HORIZON, MODEL_DIR
from app.model.purged_cv import purged_kfold_indices


def fit_lgbm(panel: pd.DataFrame, feature_cols: List[str],
             target_col: str = "y_fwd",
             n_splits: int = 5,
             params: Optional[dict] = None) -> Dict:
    """Train + cross-validate. Returns dict with model, CV metrics, feature importance."""
    df = panel.dropna(subset=[target_col]).copy()
    df["date"] = pd.to_datetime(df["date"])
    X = df[feature_cols]
    y = df[target_col].astype(float)

    p = {
        "objective": "regression",
        "metric": "rmse",
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_data_in_leaf": 200,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.85,
        "bagging_freq": 5,
        "lambda_l2": 1.0,
        "verbose": -1,
    }
    if params:
        p.update(params)

    folds = purged_kfold_indices(df["date"], n_splits=n_splits,
                                 horizon_days=FORWARD_HORIZON,
                                 embargo_days=EMBARGO_DAYS)

    fold_metrics = []
    oof = pd.Series(np.nan, index=df.index)
    for k, (tr, te) in enumerate(folds):
        Xtr, ytr = X.iloc[tr], y.iloc[tr]
        Xte, yte = X.iloc[te], y.iloc[te]
        if len(Xte) == 0 or len(Xtr) == 0:
            continue
        model = lgb.train(
            p, lgb.Dataset(Xtr, label=ytr), num_boost_round=600,
            valid_sets=[lgb.Dataset(Xte, label=yte)],
            callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
        )
        pred = model.predict(Xte, num_iteration=model.best_iteration)
        oof.iloc[te] = pred
        # IC per date in this fold (cross-sectional Spearman)
        sub = df.iloc[te].assign(pred=pred)
        ic_per_date = sub.groupby("date").apply(
            lambda g: spearmanr(g["pred"], g[target_col])[0]
            if len(g) > 5 else np.nan
        )
        ic_mean = float(ic_per_date.mean(skipna=True))
        rmse = float(np.sqrt(np.mean((pred - yte.values) ** 2)))
        fold_metrics.append({"fold": k, "n_train": len(tr), "n_test": len(te),
                             "ic_mean": ic_mean, "rmse": rmse,
                             "best_iter": model.best_iteration})
        print(f"  Fold {k}: n_train={len(tr):,} n_test={len(te):,} "
              f"IC={ic_mean:+.4f} RMSE={rmse:.4f} iter={model.best_iteration}")

    # Final model on all data (smaller boost rounds — same hyperparams)
    final = lgb.train(p, lgb.Dataset(X, label=y),
                      num_boost_round=int(np.mean([m["best_iter"] for m in fold_metrics])
                                          if fold_metrics else 300))

    # Feature importance
    fi = pd.DataFrame({
        "feature": feature_cols,
        "gain": final.feature_importance(importance_type="gain"),
        "split": final.feature_importance(importance_type="split"),
    }).sort_values("gain", ascending=False)

    # Out-of-fold IC by date
    oof_df = df.copy()
    oof_df["pred"] = oof
    oof_ic = (oof_df.dropna(subset=["pred"]).groupby("date")
              .apply(lambda g: spearmanr(g["pred"], g[target_col])[0]
                     if len(g) > 5 else np.nan))

    return {
        "model": final,
        "feature_cols": feature_cols,
        "fold_metrics": fold_metrics,
        "oof_ic": oof_ic,
        "oof_ic_mean": float(oof_ic.mean(skipna=True)),
        "oof_ic_std": float(oof_ic.std(skipna=True)),
        "feature_importance": fi,
    }


def save_model(result: Dict, path: Optional[Path] = None) -> Path:
    path = path or (MODEL_DIR / "lgbm_latest.pkl")
    joblib.dump({
        "model": result["model"],
        "feature_cols": result["feature_cols"],
        "oof_ic_mean": result["oof_ic_mean"],
        "fold_metrics": result["fold_metrics"],
    }, path)
    # Also save feature importance and OOF IC for reporting
    result["feature_importance"].to_csv(MODEL_DIR / "feature_importance.csv", index=False)
    result["oof_ic"].to_csv(MODEL_DIR / "oof_ic_by_date.csv")
    return path


def load_model(path: Optional[Path] = None) -> Dict:
    path = path or (MODEL_DIR / "lgbm_latest.pkl")
    return joblib.load(path)


def predict(panel: pd.DataFrame, bundle: Dict) -> pd.Series:
    cols = bundle["feature_cols"]
    model = bundle["model"]
    return pd.Series(model.predict(panel[cols]), index=panel.index)
