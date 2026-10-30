"""Baseline models for PM2.5 estimation (Stage 5).

Models:
  1. Persistence     — previous month's PM2.5 as prediction
  2. Climatology     — station × month mean from training data
  3. Linear Regression — scikit-learn, fitted on train only
  4. Random Forest   — scikit-learn, Tier A and Tier B variants

All models follow the same interface:
  fit(X_train, y_train) -> model
  predict(X_test) -> np.ndarray

Scalers and imputers are fitted on TRAIN data only (no leakage).
NaN columns (MAIAC, CAMS) are handled by RF's native NaN support
via sklearn's HistGradientBoosting or by median imputation (train-only).
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

logger = logging.getLogger("pm25")

RANDOM_SEED = 42


# ── Persistence ──────────────────────────────────────────────────────────────

def predict_persistence(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """Use the previous month's PM2.5 as prediction.

    For each test row, look up the same station's PM2.5 from the prior month
    in the training set. If not found, fall back to the training mean.

    Args:
        train: Training DataFrame with station_id, year, month, pm25_daily_mean.
        test: Test DataFrame.

    Returns:
        Array of predictions aligned with test row order.
    """
    train_lookup = {}
    for _, row in train.iterrows():
        key = (str(row["station_id"]), int(row["year"]), int(row["month"]))
        train_lookup[key] = row["pm25_daily_mean"]

    fallback = train["pm25_daily_mean"].mean()
    preds = []
    for _, row in test.iterrows():
        y, m = int(row["year"]), int(row["month"])
        # Previous month
        prev_m = m - 1 if m > 1 else 12
        prev_y = y if m > 1 else y - 1
        key = (str(row["station_id"]), prev_y, prev_m)
        preds.append(train_lookup.get(key, fallback))

    return np.array(preds)


# ── Climatology ───────────────────────────────────────────────────────────────

class ClimatologyModel:
    """Station × calendar-month mean PM2.5 from training data."""

    def __init__(self) -> None:
        self._lookup: dict[tuple, float] = {}
        self._global_mean: float = 0.0

    def fit(self, train: pd.DataFrame) -> "ClimatologyModel":
        """Compute station × month means from training data."""
        self._global_mean = train["pm25_daily_mean"].mean()
        grp = train.groupby(["station_id", "month"])["pm25_daily_mean"].mean()
        self._lookup = {(str(k[0]), int(k[1])): v for k, v in grp.items()}
        return self

    def predict(self, test: pd.DataFrame) -> np.ndarray:
        """Predict using station × month climatology."""
        preds = []
        for _, row in test.iterrows():
            key = (str(row["station_id"]), int(row["month"]))
            preds.append(self._lookup.get(key, self._global_mean))
        return np.array(preds)


# ── Feature helpers ───────────────────────────────────────────────────────────

# Columns never used as model inputs
META_COLS = [
    "station_id", "year", "month", "season", "state",
    "latitude", "longitude", "pm25_daily_mean", "pm25_daily_std",
    "n_valid_days", "cloud_fraction_bin", "day_of_year",
]


def get_feature_cols(df: pd.DataFrame) -> list[str]:
    """Return numeric feature columns (exclude meta, target, categoricals)."""
    drop = set(META_COLS)
    cols = [
        c for c in df.columns
        if c not in drop
        and pd.api.types.is_numeric_dtype(df[c])
    ]
    return cols


# ── Linear Regression ─────────────────────────────────────────────────────────

def build_linear_pipeline() -> Pipeline:
    """Ridge regression with median imputation and standard scaling.

    Imputer and scaler fitted on train only.
    """
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("model", Ridge(alpha=1.0, random_state=RANDOM_SEED)),
    ])


def fit_linear(
    train: pd.DataFrame, feature_cols: list[str]
) -> Pipeline:
    X_train = train[feature_cols].values
    y_train = train["pm25_daily_mean"].values
    pipe = build_linear_pipeline()
    pipe.fit(X_train, y_train)
    return pipe


# ── Random Forest ─────────────────────────────────────────────────────────────

def build_rf_pipeline(n_estimators: int = 300) -> Pipeline:
    """Random Forest with median imputation.

    RF does not handle NaN natively in sklearn, so we impute first.
    Imputer is fitted on train only — no leakage.
    """
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("model", RandomForestRegressor(
            n_estimators=n_estimators,
            max_features="sqrt",
            min_samples_leaf=5,
            random_state=RANDOM_SEED,
            n_jobs=-1,
        )),
    ])


def fit_rf(
    train: pd.DataFrame, feature_cols: list[str], n_estimators: int = 300
) -> Pipeline:
    X_train = train[feature_cols].values
    y_train = train["pm25_daily_mean"].values
    pipe = build_rf_pipeline(n_estimators)
    pipe.fit(X_train, y_train)
    return pipe


def predict(pipe: Pipeline, test: pd.DataFrame, feature_cols: list[str]) -> np.ndarray:
    """Run prediction from a fitted sklearn Pipeline."""
    return pipe.predict(test[feature_cols].values)
