"""End-to-end training script: build feature panel, fit LightGBM, save model.

Usage:
    .venv\\Scripts\\python.exe -m app.train
"""
from __future__ import annotations

import argparse
import time

import pandas as pd

from app.config import MODEL_DIR
from app.features.pipeline import ALL_FEATURES, build_panel
from app.model.lgbm import fit_lgbm, save_model


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2014-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--rebalance-n", type=int, default=21)
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--use-rank", action="store_true",
                        help="Use cross-sectionally ranked features instead of raw.")
    args = parser.parse_args()

    print(f"Building panel from {args.start} to {args.end or 'today'} ...")
    t0 = time.time()
    panel = build_panel(start=args.start, end=args.end,
                        rebalance_n=args.rebalance_n)
    print(f"Panel: {len(panel):,} rows, {panel['date'].nunique()} dates, "
          f"{panel['ticker'].nunique()} tickers — built in {time.time()-t0:.1f}s")

    # Save panel for reuse
    panel.to_parquet(MODEL_DIR / "feature_panel.parquet", index=False)

    feat_cols = [c + "_rk" for c in ALL_FEATURES] if args.use_rank else ALL_FEATURES
    feat_cols = [c for c in feat_cols if c in panel.columns]
    print(f"Using {len(feat_cols)} features: {feat_cols[:5]} ...")

    print("Training LightGBM with PurgedKFold ...")
    t0 = time.time()
    res = fit_lgbm(panel, feat_cols, n_splits=args.n_splits)
    print(f"Trained in {time.time()-t0:.1f}s")
    print(f"OOF IC: mean={res['oof_ic_mean']:+.4f} std={res['oof_ic_std']:.4f}")
    print()
    print("Top features by gain:")
    print(res["feature_importance"].head(15).to_string(index=False))

    path = save_model(res)
    print(f"\nModel saved → {path}")


if __name__ == "__main__":
    main()
