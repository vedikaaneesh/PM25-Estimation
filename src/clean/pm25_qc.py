"""PM2.5 quality control rules applied to hourly ground data.

Rules applied (in order):
  1. Remove physically impossible values (< 0 or > 1000 µg/m³)
  2. Remove flat-lined sensors (same value repeated > flatline_window_hours)
  3. Remove spikes (z-score > spike_zscore within a rolling window per station)

All removed records are logged to data/interim/cleaning_log.csv with
the rule that removed them. Row counts reconcile from raw to clean.

Usage:
    python -m src.clean.pm25_qc
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from src.utils.config import load_config
from src.utils.env import load_env
from src.utils.logging_config import setup_logging

load_env()
logger = setup_logging()

PM25_DIR = Path("data/raw/pm25_hourly")
OUTPUT_DIR = Path("data/interim/pm25_clean")
CLEANING_LOG_PATH = Path("data/interim/cleaning_log.csv")


def flag_impossible(df: pd.DataFrame, min_val: float, max_val: float) -> pd.Series:
    """Flag rows where PM2.5 is outside physically plausible range.

    Args:
        df: DataFrame with pm25 column.
        min_val: Minimum valid value (inclusive).
        max_val: Maximum valid value (inclusive).

    Returns:
        Boolean Series — True means the row should be removed.
    """
    return (df["pm25"] < min_val) | (df["pm25"] > max_val)


def flag_flatlines(
    df: pd.DataFrame,
    window_hours: int,
    tolerance: float,
) -> pd.Series:
    """Flag runs of identical PM2.5 values (sensor malfunction).

    A flatline is defined as the same value (within tolerance) repeated
    for more than window_hours consecutive hours.

    Args:
        df: DataFrame sorted by timestamp_utc with pm25 column.
        window_hours: Minimum run length to flag (hours).
        tolerance: Max difference considered "identical" (µg/m³).

    Returns:
        Boolean Series — True means the row is part of a flatline run.
    """
    df = df.copy()
    df["pm25_round"] = (df["pm25"] / tolerance).round() * tolerance
    # Rolling check: all values in a window equal to the current value
    flagged = pd.Series(False, index=df.index)
    for _, grp in df.groupby("station_id"):
        grp = grp.sort_values("timestamp_utc")
        val = grp["pm25_round"]
        # Detect runs using cumsum of changes
        run_id = (val != val.shift()).cumsum()
        run_len = run_id.map(run_id.value_counts())
        mask = run_len > window_hours
        flagged.loc[grp.index[mask]] = True
    return flagged


def flag_spikes(df: pd.DataFrame, z_threshold: float, window: int = 48) -> pd.Series:
    """Flag spikes using a rolling z-score per station.

    Args:
        df: DataFrame with station_id, timestamp_utc, pm25.
        z_threshold: Z-score threshold above which a value is a spike.
        window: Rolling window size in hours.

    Returns:
        Boolean Series — True means the row is a spike.
    """
    flagged = pd.Series(False, index=df.index)
    for sid, grp in df.groupby("station_id"):
        grp = grp.sort_values("timestamp_utc")
        rolling_mean = grp["pm25"].rolling(window, center=True, min_periods=12).mean()
        rolling_std = grp["pm25"].rolling(window, center=True, min_periods=12).std()
        z = (grp["pm25"] - rolling_mean) / rolling_std.replace(0, np.nan)
        spikes = z.abs() > z_threshold
        flagged.loc[grp.index[spikes]] = True
    return flagged


def run_qc(station_id: str, df: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, list[dict]]:
    """Apply all QC rules to one station's hourly data.

    Args:
        station_id: Station identifier.
        df: Hourly PM2.5 DataFrame with timestamp_utc, pm25 columns.
        cfg: Thresholds config dict (pm25_qc section).

    Returns:
        Tuple of (cleaned DataFrame, list of log dicts).
    """
    log_rows: list[dict] = []
    n_raw = len(df)
    df = df.copy()
    df["removed"] = False
    df["remove_rule"] = ""

    # Rule 1: impossible values
    mask_impossible = flag_impossible(df, cfg["min_value"], cfg["max_value"])
    df.loc[mask_impossible & ~df["removed"], "remove_rule"] = "impossible_value"
    df.loc[mask_impossible, "removed"] = True
    n_impossible = mask_impossible.sum()

    # Rule 2: flatlines (only on non-removed rows)
    working = df[~df["removed"]].copy()
    mask_flat = flag_flatlines(working, cfg["flatline_window_hours"], cfg["flatline_tolerance"])
    flat_idx = working.index[mask_flat]
    df.loc[flat_idx, "remove_rule"] = "flatline"
    df.loc[flat_idx, "removed"] = True
    n_flat = mask_flat.sum()

    # Rule 3: spikes (only on non-removed rows)
    working2 = df[~df["removed"]].copy()
    mask_spike = flag_spikes(working2, cfg["spike_zscore"])
    spike_idx = working2.index[mask_spike]
    df.loc[spike_idx, "remove_rule"] = "spike"
    df.loc[spike_idx, "removed"] = True
    n_spike = mask_spike.sum()

    n_clean = (~df["removed"]).sum()

    log_rows.append({
        "station_id": station_id,
        "n_raw": n_raw,
        "n_removed_impossible": int(n_impossible),
        "n_removed_flatline": int(n_flat),
        "n_removed_spike": int(n_spike),
        "n_clean": int(n_clean),
        "pct_removed": round((n_raw - n_clean) / n_raw * 100, 2) if n_raw > 0 else 0,
    })

    clean_df = df[~df["removed"]].drop(columns=["removed", "remove_rule", "pm25_round"], errors="ignore")
    return clean_df, log_rows


def main() -> None:
    """Run PM2.5 QC on all station files and write cleaned data + log."""
    thresholds = load_config("thresholds")
    cfg = thresholds["pm25_qc"]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_logs: list[dict] = []
    n_raw_total = 0
    n_clean_total = 0

    station_files = sorted(PM25_DIR.glob("*.csv"))
    logger.info(f"Running QC on {len(station_files)} station files ...")

    for f in station_files:
        sid = f.stem
        df = pd.read_csv(f, parse_dates=["timestamp_utc", "timestamp_ist"])
        n_raw_total += len(df)

        clean_df, log_rows = run_qc(sid, df, cfg)
        n_clean_total += len(clean_df)
        all_logs.extend(log_rows)

        out_path = OUTPUT_DIR / f"{sid}.csv"
        clean_df.to_csv(out_path, index=False)

    # Write cleaning log
    log_df = pd.DataFrame(all_logs)
    CLEANING_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_df.to_csv(CLEANING_LOG_PATH, index=False)

    # Row count reconciliation
    logger.info(f"\n{'='*55}")
    logger.info(f"ROW COUNT RECONCILIATION")
    logger.info(f"  Raw rows:         {n_raw_total:>10,}")
    logger.info(f"  Clean rows:       {n_clean_total:>10,}")
    logger.info(f"  Removed total:    {n_raw_total - n_clean_total:>10,}  "
                f"({(n_raw_total - n_clean_total)/n_raw_total*100:.2f}%)")
    logger.info(f"  - Impossible:     {log_df['n_removed_impossible'].sum():>10,}")
    logger.info(f"  - Flatline:       {log_df['n_removed_flatline'].sum():>10,}")
    logger.info(f"  - Spike:          {log_df['n_removed_spike'].sum():>10,}")
    logger.info(f"{'='*55}")
    logger.info(f"Cleaning log saved to {CLEANING_LOG_PATH}")


if __name__ == "__main__":
    main()
