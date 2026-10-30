"""Ingest ground PM2.5 from XKDR API and standardize to unified schema.

Fetches hourly PM2.5 for usable stations (meeting completeness threshold)
and standardizes to:
    station_id, timestamp_utc, timestamp_ist, pm25, unit, source, quality_flag

Saves to data/raw/pm25_hourly/ with a manifest (row counts, date range,
retrieval date). Data is fetched per-station in monthly chunks to respect
API limits and make the script resumable.

Usage:
    python -m src.ingest.ingest_pm25
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from src.utils.config import load_config
from src.utils.env import load_env
from src.utils.logging_config import setup_logging

load_env()
logger = setup_logging()

XKDR_BASE_URL = "https://airquality.xkdr.org/v1"
API_KEY = os.environ.get("XKDR_API_KEY") or "aqi_demo_wbf92Qx21zX-Wa_Tg8Dx1nXe"
STATIONS_PATH = Path("data/interim/completeness_overall.csv")
MERGED_PATH = Path("data/interim/stations_merged.csv")
OUTPUT_DIR = Path("data/raw/pm25_hourly")
MANIFEST_PATH = Path("data/raw/pm25_manifest.csv")
IST_OFFSET = pd.Timedelta(hours=5, minutes=30)

def load_usable_stations() -> pd.DataFrame:
    """Load stations meeting the 70% completeness threshold."""
    if not STATIONS_PATH.exists():
        logger.error(f"Completeness file not found: {STATIONS_PATH}")
        logger.error("Run completeness_audit first.")
        return pd.DataFrame()

    comp = pd.read_csv(STATIONS_PATH)
    usable = comp[comp["meets_threshold"]]["station_id"].astype(str).tolist()

    merged = pd.read_csv(MERGED_PATH)
    merged["station_id"] = merged["station_id"].astype(str)
    usable_df = merged[merged["station_id"].isin(usable)].copy()

    logger.info(f"Loaded {len(usable_df)} usable stations")
    return usable_df


def fetch_pm25_month(
    station_id: str,
    year: int,
    month: int,
    api_key: str = API_KEY,
) -> pd.DataFrame:
    """Fetch hourly PM2.5 for one station-month from XKDR.

    Args:
        station_id: XKDR station ID (e.g. site_5105).
        year: Year.
        month: Month.
        api_key: XKDR API bearer token.

    Returns:
        DataFrame with columns: station_id, datetime_ist, pm25.
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    start = f"{year}-{month:02d}-01"
    # End date: last day of month
    end = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
    end_str = end.strftime("%Y-%m-%d")

    params = {
        "station": station_id,
        "parameter": "PM2.5",
        "start": start,
        "end": end_str,
        "format": "csv",
    }
    resp = requests.get(
        f"{XKDR_BASE_URL}/measurements",
        headers=headers,
        params=params,
        timeout=120,
    )
    if resp.status_code != 200:
        logger.warning(
            f"API error {resp.status_code} for {station_id} {start}: "
            f"{resp.text[:200]}"
        )
        return pd.DataFrame()

    if not resp.text.strip():
        return pd.DataFrame()

    df = pd.read_csv(pd.io.common.StringIO(resp.text))

    # Normalize columns
    for col in df.columns:
        lower = col.lower()
        if "station" in lower and "id" in lower:
            df = df.rename(columns={col: "station_id"})
        elif lower in ("collected_at", "period_start", "time", "datetime"):
            df = df.rename(columns={col: "datetime_ist"})
        elif lower == "value":
            df = df.rename(columns={col: "pm25"})

    if "datetime_ist" in df.columns:
        df["datetime_ist"] = pd.to_datetime(df["datetime_ist"], errors="coerce")
    if "pm25" not in df.columns:
        val_cols = [c for c in df.columns if "value" in c.lower()]
        if val_cols:
            df = df.rename(columns={val_cols[0]: "pm25"})

    return df


def standardize_pm25(df: pd.DataFrame, source: str = "cpcb_caaqm") -> pd.DataFrame:
    """Convert raw XKDR PM2.5 to unified schema.

    Args:
        df: Raw DataFrame with station_id, datetime_ist, pm25.
        source: Data source label.

    Returns:
        DataFrame with: station_id, timestamp_utc, timestamp_ist,
        pm25, unit, source, quality_flag.
    """
    if df.empty:
        return pd.DataFrame()

    df = df.copy()
    df["timestamp_ist"] = df["datetime_ist"]
    df["timestamp_utc"] = df["timestamp_ist"] - IST_OFFSET
    df["pm25"] = df["pm25"].astype(float)
    df["unit"] = "ug/m3"
    df["source"] = source
    df["quality_flag"] = "raw"  # QC applied in Stage 4

    # Determine source type
    sid = str(df["station_id"].iloc[0])
    if sid.startswith("DS"):
        df["source"] = "us_embassy"

    cols = [
        "station_id", "timestamp_utc", "timestamp_ist",
        "pm25", "unit", "source", "quality_flag",
    ]
    return df[cols]


def main() -> None:
    """Fetch and standardize PM2.5 for all usable stations."""
    stations = load_usable_stations()
    if stations.empty:
        return

    config = load_config("dates")
    start_date = pd.Timestamp(config["study_period"]["start"])
    end_date = pd.Timestamp(config["study_period"]["end"])

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest_rows = []
    total_rows = 0

    for _, station in stations.iterrows():
        sid = str(station["station_id"])
        state = station.get("state", "Unknown")
        station_file = OUTPUT_DIR / f"{sid}.csv"

        # Resumability: skip if file exists with data
        if station_file.exists():
            existing = pd.read_csv(station_file)
            if len(existing) > 0:
                logger.info(f"  Skip {sid} (already ingested, {len(existing)} rows)")
                manifest_rows.append({
                    "station_id": sid,
                    "file": str(station_file),
                    "row_count": len(existing),
                    "date_range": f"{existing['timestamp_ist'].min()} to {existing['timestamp_ist'].max()}",
                    "retrieval_date": datetime.now().isoformat(),
                })
                total_rows += len(existing)
                continue

        all_months = []
        current = start_date
        while current <= end_date:
            year = current.year
            month = current.month
            logger.info(f"  {sid} {state} {year}-{month:02d} ...")
            df = fetch_pm25_month(sid, year, month)
            if not df.empty:
                all_months.append(df)
            current = current + pd.offsets.MonthBegin(1)

        if not all_months:
            logger.warning(f"  No data for {sid}")
            continue

        combined = pd.concat(all_months, ignore_index=True)
        standardized = standardize_pm25(combined)
        standardized.to_csv(station_file, index=False)

        n = len(standardized)
        total_rows += n
        date_range = (
            f"{standardized['timestamp_ist'].min()} to "
            f"{standardized['timestamp_ist'].max()}"
        )
        manifest_rows.append({
            "station_id": sid,
            "file": str(station_file),
            "row_count": n,
            "date_range": date_range,
            "retrieval_date": datetime.now().isoformat(),
        })
        logger.info(f"  {sid}: {n} rows saved")

    # Save manifest
    manifest = pd.DataFrame(manifest_rows)
    manifest.to_csv(MANIFEST_PATH, index=False)
    logger.info(f"\nManifest saved to {MANIFEST_PATH}")
    logger.info(f"Total stations: {len(manifest)}")
    logger.info(f"Total rows: {total_rows}")


if __name__ == "__main__":
    main()
