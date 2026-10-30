"""Feature engineering for PM2.5 estimation models.

Builds Tier A (full) and Tier B (fallback, no satellite) feature sets
from the aligned monthly dataset. Adds:
  - Cyclical day-of-year encoding (sin/cos)
  - Monsoon season label (one-hot or ordinal)
  - PM2.5 lags (1, 2, 3 months per station — proxy for day lags at monthly level)
  - Wind speed from u/v components
  - Relative humidity from temperature and dewpoint
  - Satellite-availability flag (cloud_fraction threshold)
  - Cloud-fraction bin
  - Valid pixel count features

No imputation here — NaNs are kept for tree models.
Imputation (train-only) will happen inside the model pipeline.

Output:
  data/processed/features_tier_a.csv
  data/processed/features_tier_b.csv
  data/processed/features_metadata.csv  (column types, tier membership)

Usage:
    python -m src.features.build_features
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from src.utils.config import load_config
from src.utils.env import load_env
from src.utils.logging_config import setup_logging
from src.utils.seasons import cyclical_encode_doy, SEASON_MAP

load_env()
logger = setup_logging()

ALIGNED_PATH = Path("data/interim/aligned_monthly.csv")
OUTPUT_DIR = Path("data/processed")
RANDOM_SEED = 42


def add_cyclical_doy(df: pd.DataFrame) -> pd.DataFrame:
    """Add day-of-year sine/cosine from year-month midpoint."""
    df = df.copy()
    # Use 15th of each month as representative day
    df["day_of_year"] = df.apply(
        lambda r: pd.Timestamp(int(r["year"]), int(r["month"]), 15).day_of_year,
        axis=1,
    )
    df["doy_sin"], df["doy_cos"] = cyclical_encode_doy(df["day_of_year"])
    return df


def add_wind_speed(df: pd.DataFrame) -> pd.DataFrame:
    """Compute wind speed from u/v components."""
    df = df.copy()
    u = df.get("era5_u_wind")
    v = df.get("era5_v_wind")
    if u is not None and v is not None:
        df["era5_wind_speed"] = np.sqrt(u ** 2 + v ** 2)
    return df


def add_relative_humidity(df: pd.DataFrame) -> pd.DataFrame:
    """Compute relative humidity from temperature and dewpoint (both in K).

    Uses the Magnus formula approximation.
    RH = 100 * exp(17.625 * Td / (243.04 + Td)) /
              exp(17.625 * T  / (243.04 + T))
    where T, Td are in Celsius.
    """
    df = df.copy()
    t_col = "era5_temperature"
    td_col = "era5_dewpoint"
    if t_col in df.columns and td_col in df.columns:
        T_c = df[t_col] - 273.15
        Td_c = df[td_col] - 273.15
        rh = 100 * np.exp(17.625 * Td_c / (243.04 + Td_c)) / \
             np.exp(17.625 * T_c / (243.04 + T_c))
        df["era5_relative_humidity"] = rh.clip(0, 100)
    return df


def add_satellite_flags(df: pd.DataFrame, cloud_threshold: float = 0.3) -> pd.DataFrame:
    """Add satellite availability flag and cloud fraction bin.

    satellite_available = 1 if cloud_fraction < threshold, else 0.
    Cloud fraction bins: 0–0.2 (clear), 0.2–0.4 (partly), 0.4–0.6, 0.6–0.8, 0.8–1.0.
    """
    df = df.copy()
    if "tropomi_cloud_fraction" in df.columns:
        df["satellite_available"] = (
            df["tropomi_cloud_fraction"] < cloud_threshold
        ).astype(int)
        df["cloud_fraction_bin"] = pd.cut(
            df["tropomi_cloud_fraction"].fillna(1.0),
            bins=[0, 0.2, 0.4, 0.6, 0.8, 1.01],
            labels=["0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0"],
            include_lowest=True,
        )
    else:
        df["satellite_available"] = 0
        df["cloud_fraction_bin"] = "unknown"
    return df


def add_pm25_lags(df: pd.DataFrame, lags: list[int]) -> pd.DataFrame:
    """Add lagged PM2.5 values per station (monthly lags).

    Note: At monthly resolution, lag-1 = previous month. This serves as
    a proxy until we have daily lags in Stage 4 daily pipeline.

    Args:
        df: DataFrame with station_id, year, month, pm25_daily_mean.
        lags: List of lag integers (months back).

    Returns:
        DataFrame with pm25_lag_N columns.
    """
    df = df.copy().sort_values(["station_id", "year", "month"])
    for lag in lags:
        df[f"pm25_lag_{lag}"] = (
            df.groupby("station_id")["pm25_daily_mean"]
            .shift(lag)
        )
    return df


def add_met_lags(df: pd.DataFrame) -> pd.DataFrame:
    """Add 1-month lags for temperature and relative humidity per station."""
    df = df.copy().sort_values(["station_id", "year", "month"])
    for col in ["era5_temperature", "era5_relative_humidity"]:
        if col in df.columns:
            df[f"{col}_lag_1"] = df.groupby("station_id")[col].shift(1)
    return df


def build_tier_a(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Select and return Tier A features plus target column."""
    tier_a_cfg = config["tier_a"]
    keep_cols = ["station_id", "year", "month", "season",
                 "state", "latitude", "longitude",
                 "pm25_daily_mean", "n_valid_days"]

    # Satellite
    for col in tier_a_cfg.get("satellite", []):
        if col in df.columns:
            keep_cols.append(col)

    # Reanalysis
    for col in tier_a_cfg.get("reanalysis", []):
        if col in df.columns:
            keep_cols.append(col)

    # Meteorology (may have been renamed)
    met_map = {
        "era5_temperature": "era5_temperature",
        "era5_dewpoint_temp": "era5_dewpoint",
        "era5_u_wind": "era5_u_wind",
        "era5_v_wind": "era5_v_wind",
        "era5_precipitation": "era5_precipitation",
        "era5_blh": "era5_blh",
        "era5_relative_humidity": "era5_relative_humidity",
        "era5_wind_speed": "era5_wind_speed",
    }
    for cfg_name, actual_name in met_map.items():
        if actual_name in df.columns and actual_name not in keep_cols:
            keep_cols.append(actual_name)

    # Temporal
    for col in ["doy_sin", "doy_cos", "day_of_year"]:
        if col in df.columns:
            keep_cols.append(col)

    # Lags
    lag_cols = [c for c in df.columns if "lag" in c]
    keep_cols.extend(lag_cols)

    # Flags
    for col in ["satellite_available", "cloud_fraction_bin",
                "s5p_no2_pixel_count"]:
        if col in df.columns:
            keep_cols.append(col)

    existing = [c for c in keep_cols if c in df.columns]
    return df[existing].copy()


def build_tier_b(df: pd.DataFrame) -> pd.DataFrame:
    """Select Tier B features (no satellite, for cloudy days)."""
    keep_cols = ["station_id", "year", "month", "season",
                 "state", "latitude", "longitude",
                 "pm25_daily_mean", "n_valid_days"]

    # Only reanalysis and met — NO satellite columns
    for col in df.columns:
        is_satellite = any(k in col for k in
                           ["tropomi", "maiac", "s5p"])
        is_target_or_key = col in keep_cols
        if not is_satellite and not is_target_or_key:
            keep_cols.append(col)

    existing = [c for c in keep_cols if c in df.columns]
    return df[existing].copy()


def save_metadata(tier_a: pd.DataFrame, tier_b: pd.DataFrame) -> None:
    """Save column metadata CSV listing tier membership and types."""
    all_cols = set(tier_a.columns) | set(tier_b.columns)
    rows = []
    for col in sorted(all_cols):
        rows.append({
            "column": col,
            "in_tier_a": col in tier_a.columns,
            "in_tier_b": col in tier_b.columns,
            "dtype_tier_a": str(tier_a[col].dtype) if col in tier_a.columns else "",
            "null_pct_tier_a": round(tier_a[col].isnull().mean() * 100, 1)
            if col in tier_a.columns else 100.0,
        })
    pd.DataFrame(rows).to_csv(
        OUTPUT_DIR / "features_metadata.csv", index=False
    )


def main() -> None:
    """Build Tier A and Tier B feature sets from aligned monthly data."""
    if not ALIGNED_PATH.exists():
        logger.error(f"Aligned data not found: {ALIGNED_PATH}. Run align_datasets first.")
        return

    df = pd.read_csv(ALIGNED_PATH)
    logger.info(f"Loaded {len(df):,} rows, {df.shape[1]} columns")

    # Feature engineering
    df = add_cyclical_doy(df)
    df = add_wind_speed(df)
    df = add_relative_humidity(df)
    df = add_satellite_flags(df)
    df = add_pm25_lags(df, lags=[1, 2, 3])
    df = add_met_lags(df)

    config = load_config("features")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    tier_a = build_tier_a(df, config)
    tier_b = build_tier_b(df)

    # Drop rows with no PM2.5 target
    tier_a = tier_a.dropna(subset=["pm25_daily_mean"])
    tier_b = tier_b.dropna(subset=["pm25_daily_mean"])

    tier_a.to_csv(OUTPUT_DIR / "features_tier_a.csv", index=False)
    tier_b.to_csv(OUTPUT_DIR / "features_tier_b.csv", index=False)
    save_metadata(tier_a, tier_b)

    logger.info(f"\n{'='*55}")
    logger.info(f"Tier A: {len(tier_a):,} rows, {tier_a.shape[1]} columns")
    logger.info(f"Tier B: {len(tier_b):,} rows, {tier_b.shape[1]} columns")

    # Null report
    logger.info("\nTier A null %:")
    null_a = (tier_a.isnull().mean() * 100).round(1)
    for col, pct in null_a[null_a > 0].items():
        logger.info(f"  {col:45s}: {pct:.1f}%")
    logger.info(f"{'='*55}")


if __name__ == "__main__":
    main()
