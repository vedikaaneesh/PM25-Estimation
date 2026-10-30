"""Spatiotemporal alignment of satellite, reanalysis, and ground PM2.5.

Builds two target definitions:
  (a) PM2.5 averaged over satellite overpass window 12:00-15:00 IST
  (b) PM2.5 daily mean

Merges ground PM2.5 with all GEE monthly extracts on (station_id, year, month).
Handles timezones explicitly (IST = UTC + 5h30m).
Writes an off-by-one-day timezone unit test (tested separately).

Output:
  data/interim/aligned_monthly.csv  — one row per station-month
  data/interim/aligned_overpass.csv — one row per station-month using overpass window

Usage:
    python -m src.align.align_datasets
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import numpy as np

from src.utils.config import load_config
from src.utils.env import load_env
from src.utils.gee_loader import load_all_gee
from src.utils.logging_config import setup_logging
from src.utils.seasons import add_temporal_columns, SEASON_MAP

load_env()
logger = setup_logging()

PM25_CLEAN_DIR = Path("data/interim/pm25_clean")
STATIONS_PATH = Path("data/interim/stations_merged.csv")
OUTPUT_DIR = Path("data/interim")

# TROPOMI ascending node overpass time over South India is ~13:30 IST
# Use 12:00–15:00 IST as the overpass window (conservative ±1.5h)
OVERPASS_START_IST = 12
OVERPASS_END_IST = 15

GEE_DATASETS = [
    "s5p_no2", "s5p_co", "s5p_so2", "s5p_hcho", "s5p_aer_ai",
    "maiac_aod", "era5_land", "era5_blh", "cams_aod",
]


def load_pm25_daily_and_overpass() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load cleaned hourly PM2.5 and compute daily + overpass aggregates.

    Returns:
        Tuple of (daily_df, overpass_df), both with columns:
        station_id, year, month, pm25_daily/pm25_overpass, n_hours.
    """
    daily_rows, overpass_rows = [], []

    for f in sorted(PM25_CLEAN_DIR.glob("*.csv")):
        df = pd.read_csv(f, parse_dates=["timestamp_utc", "timestamp_ist"])
        sid = f.stem

        # Daily mean (IST date)
        df["date_ist"] = df["timestamp_ist"].dt.normalize()
        daily = (
            df.groupby("date_ist")["pm25"]
            .agg(pm25_daily="mean", n_hours="count")
            .reset_index()
        )
        daily = daily[daily["n_hours"] >= 18]
        daily["station_id"] = sid
        daily["year"] = daily["date_ist"].dt.year
        daily["month"] = daily["date_ist"].dt.month
        daily_rows.append(daily)

        # Overpass window mean (12:00-15:00 IST)
        df["hour_ist"] = df["timestamp_ist"].dt.hour
        overpass = df[
            (df["hour_ist"] >= OVERPASS_START_IST) &
            (df["hour_ist"] < OVERPASS_END_IST)
        ]
        if overpass.empty:
            continue
        overpass = (
            overpass.groupby("date_ist")["pm25"]
            .agg(pm25_overpass="mean", n_hours="count")
            .reset_index()
        )
        overpass = overpass[overpass["n_hours"] >= 2]
        overpass["station_id"] = sid
        overpass["year"] = overpass["date_ist"].dt.year
        overpass["month"] = overpass["date_ist"].dt.month
        overpass_rows.append(overpass)

    daily_df = pd.concat(daily_rows, ignore_index=True) if daily_rows else pd.DataFrame()
    overpass_df = pd.concat(overpass_rows, ignore_index=True) if overpass_rows else pd.DataFrame()

    # Aggregate to monthly
    def monthly_agg(df: pd.DataFrame, pm25_col: str) -> pd.DataFrame:
        return (
            df.groupby(["station_id", "year", "month"])
            .agg(
                pm25_mean=(pm25_col, "mean"),
                pm25_std=(pm25_col, "std"),
                n_days=(pm25_col, "count"),
            )
            .reset_index()
        )

    daily_monthly = monthly_agg(daily_df, "pm25_daily")
    daily_monthly.rename(columns={"pm25_mean": "pm25_daily_mean",
                                   "pm25_std": "pm25_daily_std",
                                   "n_days": "n_valid_days"}, inplace=True)

    overpass_monthly = monthly_agg(overpass_df, "pm25_overpass")
    overpass_monthly.rename(columns={"pm25_mean": "pm25_overpass_mean",
                                      "pm25_std": "pm25_overpass_std",
                                      "n_days": "n_overpass_days"}, inplace=True)

    logger.info(f"PM2.5 daily monthly rows: {len(daily_monthly):,}")
    logger.info(f"PM2.5 overpass monthly rows: {len(overpass_monthly):,}")
    return daily_monthly, overpass_monthly


def merge_gee_data(base: pd.DataFrame) -> pd.DataFrame:
    """Left-join all GEE datasets onto the PM2.5 base on station_id/year/month.

    Args:
        base: DataFrame with station_id, year, month as keys.

    Returns:
        Merged DataFrame with all GEE columns appended.
    """
    gee_all = load_all_gee()
    merged = base.copy()

    for dataset, gee_df in gee_all.items():
        if dataset not in GEE_DATASETS or gee_df.empty:
            logger.warning(f"  {dataset}: not available, skipping")
            continue

        # Drop buffer_m from join key (not needed)
        gee_df = gee_df.drop(columns=["buffer_m"], errors="ignore")
        gee_df["station_id"] = gee_df["station_id"].astype(str)

        # Rename valid_pixel_count to be dataset-specific
        if "valid_pixel_count" in gee_df.columns:
            gee_df = gee_df.rename(
                columns={"valid_pixel_count": f"{dataset}_pixel_count"}
            )

        merged = merged.merge(
            gee_df,
            on=["station_id", "year", "month"],
            how="left",
            suffixes=("", f"_{dataset}"),
        )
        logger.info(f"  Joined {dataset}: {len(gee_df):,} rows")

    return merged


def add_station_metadata(df: pd.DataFrame) -> pd.DataFrame:
    """Add state, latitude, longitude from station inventory."""
    stations = pd.read_csv(STATIONS_PATH)
    stations["station_id"] = stations["station_id"].astype(str)
    keep = ["station_id", "state", "city", "latitude", "longitude"]
    stations = stations[[c for c in keep if c in stations.columns]]
    return df.merge(stations, on="station_id", how="left")


def add_season(df: pd.DataFrame) -> pd.DataFrame:
    """Add season column from month."""
    df = df.copy()
    df["season"] = df["month"].map(SEASON_MAP)
    return df


def main() -> None:
    """Run alignment and save analysis-ready monthly datasets."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Loading cleaned PM2.5 ...")
    daily_monthly, overpass_monthly = load_pm25_daily_and_overpass()

    logger.info("Merging GEE data (daily mean PM2.5 target) ...")
    aligned_daily = merge_gee_data(daily_monthly)
    aligned_daily = add_station_metadata(aligned_daily)
    aligned_daily = add_season(aligned_daily)

    logger.info("Merging GEE data (overpass PM2.5 target) ...")
    aligned_overpass = merge_gee_data(overpass_monthly)
    aligned_overpass = add_station_metadata(aligned_overpass)
    aligned_overpass = add_season(aligned_overpass)

    # Save
    out_daily = OUTPUT_DIR / "aligned_monthly.csv"
    out_overpass = OUTPUT_DIR / "aligned_overpass.csv"
    aligned_daily.to_csv(out_daily, index=False)
    aligned_overpass.to_csv(out_overpass, index=False)

    logger.info(f"\n{'='*55}")
    logger.info(f"Aligned daily: {len(aligned_daily):,} rows, "
                f"{aligned_daily.shape[1]} columns -> {out_daily}")
    logger.info(f"Aligned overpass: {len(aligned_overpass):,} rows, "
                f"{aligned_overpass.shape[1]} columns -> {out_overpass}")
    logger.info(f"{'='*55}")

    # Quick null summary for key columns
    key_cols = [c for c in aligned_daily.columns
                if any(k in c for k in ["pm25", "tropomi", "maiac", "era5", "cams"])]
    null_pct = (aligned_daily[key_cols].isnull().mean() * 100).round(1)
    logger.info("\nNull % per key column (aligned_monthly):")
    for col, pct in null_pct.items():
        logger.info(f"  {col:45s}: {pct:5.1f}%")


if __name__ == "__main__":
    main()
