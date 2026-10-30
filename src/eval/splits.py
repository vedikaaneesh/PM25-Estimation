"""Train/test split strategies for PM2.5 models.

Three strategies to prevent data leakage:
  1. Temporal split: train on 2021-2023, test on 2024.
  2. Spatial split: leave-one-station-out (LOSO) and spatially blocked K-fold.
  3. Combined: held-out stations AND held-out final year.

No random row-wise splits. All splits are group-aware (by station).
"""
from __future__ import annotations

import logging
from typing import Iterator

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

logger = logging.getLogger("pm25")

TEST_YEAR = 2024


def temporal_split(
    df: pd.DataFrame,
    test_year: int = TEST_YEAR,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Train on years < test_year, test on test_year.

    Args:
        df: Full feature DataFrame with 'year' column.
        test_year: The held-out test year.

    Returns:
        Tuple (train_df, test_df).
    """
    train = df[df["year"] < test_year].copy()
    test = df[df["year"] == test_year].copy()
    logger.info(f"Temporal split: train={len(train):,}, test={len(test):,} "
                f"(test year={test_year})")
    return train, test


def loso_splits(
    df: pd.DataFrame,
) -> Iterator[tuple[pd.DataFrame, pd.DataFrame, str]]:
    """Leave-one-station-out splits.

    Yields (train_df, test_df, station_id) for each station.

    Args:
        df: Feature DataFrame with 'station_id' column.

    Yields:
        Tuples of (train, test, station_id).
    """
    stations = df["station_id"].unique()
    for sid in stations:
        train = df[df["station_id"] != sid].copy()
        test = df[df["station_id"] == sid].copy()
        yield train, test, sid


def spatial_block_kfold(
    df: pd.DataFrame,
    n_splits: int = 5,
) -> Iterator[tuple[pd.DataFrame, pd.DataFrame, int]]:
    """Spatially blocked group K-fold: groups = station_id.

    Ensures all records from one station are always in the same fold.
    Yields (train_df, test_df, fold_number).

    Args:
        df: Feature DataFrame with 'station_id' column.
        n_splits: Number of folds.

    Yields:
        Tuples of (train, test, fold_number).
    """
    groups = df["station_id"]
    gkf = GroupKFold(n_splits=n_splits)
    X_dummy = np.zeros(len(df))  # GroupKFold only needs groups

    for fold, (train_idx, test_idx) in enumerate(
        gkf.split(X_dummy, groups=groups)
    ):
        yield df.iloc[train_idx].copy(), df.iloc[test_idx].copy(), fold


def combined_split(
    df: pd.DataFrame,
    held_out_station_fraction: float = 0.2,
    test_year: int = TEST_YEAR,
    random_seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Hold out both a fraction of stations and the final year.

    Stations chosen for hold-out are removed from both train and test.
    Test = held-out stations in test_year period.
    Train = remaining stations in train years.

    Args:
        df: Feature DataFrame.
        held_out_station_fraction: Fraction of stations to hold out.
        test_year: Year to hold out.
        random_seed: For reproducible station selection.

    Returns:
        Tuple (train_df, test_df).
    """
    rng = np.random.default_rng(random_seed)
    all_stations = df["station_id"].unique()
    n_hold = max(1, int(len(all_stations) * held_out_station_fraction))
    held_out = rng.choice(all_stations, size=n_hold, replace=False)

    test = df[
        df["station_id"].isin(held_out) & (df["year"] == test_year)
    ].copy()
    train = df[
        ~df["station_id"].isin(held_out) & (df["year"] < test_year)
    ].copy()

    logger.info(
        f"Combined split: held-out stations={len(held_out)}, "
        f"train={len(train):,}, test={len(test):,}"
    )
    return train, test
