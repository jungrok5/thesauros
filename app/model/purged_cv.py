"""Purged K-Fold with Embargo (López de Prado, AFML §7).

Why standard KFold leaks: with a 21-day forward target, an observation at
date t in train can have its label window overlap a test sample at date t'.
Without purging, the model learns from labels it will be evaluated on.

PurgedKFold:
  - For each test fold, compute the label window (date, date+horizon).
  - Drop training samples whose label window overlaps test or its embargo.

This implementation expects each row to have a `date` column from which we
derive the label window [date, date + horizon).
"""
from __future__ import annotations

from typing import Iterator, List, Tuple

import numpy as np
import pandas as pd


def purged_kfold_indices(dates: pd.Series, n_splits: int = 5,
                         horizon_days: int = 21,
                         embargo_days: int = 21) -> List[Tuple[np.ndarray, np.ndarray]]:
    """Return list of (train_idx, test_idx) for time-based folds.

    Folds are contiguous blocks of dates. For each test block we:
      1. Embargo a window of (embargo_days) on either side.
      2. Purge training samples whose label window overlaps the test block.
    """
    if dates.empty:
        return []
    dates = pd.to_datetime(dates).reset_index(drop=True)
    n = len(dates)

    # Sort indices by date
    order = dates.argsort().values
    sorted_dates = dates.iloc[order].reset_index(drop=True)

    # Split sorted indices into n_splits roughly equal contiguous chunks
    folds = np.array_split(np.arange(n), n_splits)

    out = []
    for k, test_pos in enumerate(folds):
        test_idx_sorted = test_pos
        if len(test_idx_sorted) == 0:
            continue
        test_start = sorted_dates.iloc[test_idx_sorted[0]]
        test_end = sorted_dates.iloc[test_idx_sorted[-1]]

        # Train candidates = everything not in test
        train_pos_sorted = np.setdiff1d(np.arange(n), test_idx_sorted, assume_unique=True)

        # Drop train samples whose label window [d, d + horizon] overlaps the
        # test block [test_start, test_end + horizon] expanded by embargo.
        guard_start = test_start - pd.Timedelta(days=embargo_days)
        guard_end = test_end + pd.Timedelta(days=embargo_days + horizon_days)
        train_dates = sorted_dates.iloc[train_pos_sorted]
        # A train sample's label window is [train_d, train_d + horizon].
        train_label_end = train_dates + pd.Timedelta(days=horizon_days)
        keep = ~((train_label_end >= guard_start) & (train_dates <= guard_end))
        train_pos_sorted = train_pos_sorted[keep.values]

        # Map back to original (unsorted) indices
        test_idx = order[test_idx_sorted]
        train_idx = order[train_pos_sorted]
        out.append((train_idx, test_idx))
    return out
