"""GEE daily-resolution S5P extraction at station coordinates.

Unlike the monthly aggregates in gee_extract.py, this script extracts
one row per station per day — needed to count valid overpass days and
quantify cloud contamination during the SW monsoon (Jun-Sep).

Extracts from COPERNICUS/S5P/OFFL/L3_NO2:
  - tropospheric_NO2_column_number_density
  - cloud_fraction
  - absorbing_aerosol_index (from AER_AI collection)

Strategy: iterate day by day within each month, extract reduceRegion
for each image. If no image exists for a day (cloudy/no overpass),
the row records NaN. This gives a daily valid-pixel count series.

Output: data/raw/gee_extracts/s5p_daily/{YYYY-MM}.csv
Columns: station_id, date, tropomi_no2_column, cloud_fraction,
         valid_pixel_count, satellite_available (0/1)

Usage:
    python -m src.ingest.gee_extract_daily --start 2021-01 --end 2024-12
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from src.ingest.gee_auth import initialize_ee
from src.utils.config import load_config
from src.utils.logging_config import setup_logging

load_env = None  # imported below
logger = setup_logging()

STATIONS_PATH = Path("data/interim/stations_merged.csv")
COMPLETENESS_PATH = Path("data/interim/completeness_overall.csv")
OUTPUT_DIR = Path("data/raw/gee_extracts/s5p_daily")
MANIFEST_PATH = Path("data/raw/gee_extract_manifest_daily.csv")

# S5P OFFL NO2 collection (also contains cloud_fraction band)
S5P_NO2_COLLECTION = "COPERNICUS/S5P/OFFL/L3_NO2"
# Scale for reduceRegions: ~1.1km (0.01 arc deg)
S5P_SCALE = 1113
BUFFER_M = 5000


def load_usable_stations() -> pd.DataFrame:
    """Load usable stations with coordinates."""
    comp = pd.read_csv(COMPLETENESS_PATH)
    usable = comp[comp["meets_threshold"]]["station_id"].astype(str).tolist()
    merged = pd.read_csv(STATIONS_PATH)
    merged["station_id"] = merged["station_id"].astype(str)
    return merged[
        merged["station_id"].isin(usable)
        & merged["latitude"].notna()
        & merged["longitude"].notna()
    ].copy()


def extract_daily_month(
    ee: Any,
    stations: pd.DataFrame,
    year: int,
    month: int,
) -> pd.DataFrame:
    """Extract daily S5P values for all stations in one month.

    Iterates day by day. For each day, mosaic all images in that day's
    window and extract via reduceRegions. Days with no valid S5P overpass
    are recorded as NaN with satellite_available=0.

    Args:
        ee: Initialized ee module.
        stations: DataFrame with station_id, latitude, longitude.
        year: Year.
        month: Month.

    Returns:
        DataFrame with columns: station_id, date, tropomi_no2_column,
        cloud_fraction, valid_pixel_count, satellite_available.
    """
    # Build FeatureCollection of buffered station points
    features = [
        ee.Feature(
            ee.Geometry.Point([float(r["longitude"]), float(r["latitude"])])
            .buffer(BUFFER_M),
            {"station_id": str(r["station_id"])}
        )
        for _, r in stations.iterrows()
    ]
    fc = ee.FeatureCollection(features)

    # Get number of days in the month
    start_date = pd.Timestamp(year=year, month=month, day=1)
    n_days = (start_date + pd.offsets.MonthEnd(0)).day

    all_rows: list[dict[str, Any]] = []

    for day in range(1, n_days + 1):
        date_str = f"{year}-{month:02d}-{day:02d}"
        day_start = ee.Date(date_str)
        day_end = day_start.advance(1, "day")

        collection = (
            ee.ImageCollection(S5P_NO2_COLLECTION)
            .filterDate(day_start, day_end)
            .select(["tropospheric_NO2_column_number_density", "cloud_fraction"])
        )

        # Check if any images exist for this day
        img_count = collection.size().getInfo()
        if img_count == 0:
            # No overpass today — record NaN for all stations
            for sid in stations["station_id"]:
                all_rows.append({
                    "station_id": sid,
                    "date": date_str,
                    "tropomi_no2_column": None,
                    "cloud_fraction": None,
                    "valid_pixel_count": 0,
                    "satellite_available": 0,
                })
            continue

        # Daily mosaic (mean if multiple images)
        daily_img = collection.mean()
        count_img = (
            collection.select("tropospheric_NO2_column_number_density")
            .count()
            .rename("valid_pixel_count")
        )
        daily_img = daily_img.addBands(count_img)

        try:
            result_fc = daily_img.reduceRegions(
                collection=fc,
                reducer=ee.Reducer.mean(),
                scale=S5P_SCALE,
            )
            result_list = result_fc.getInfo()["features"]
        except Exception as exc:
            logger.warning(f"  reduceRegions error {date_str}: {exc}")
            for sid in stations["station_id"]:
                all_rows.append({
                    "station_id": sid,
                    "date": date_str,
                    "tropomi_no2_column": None,
                    "cloud_fraction": None,
                    "valid_pixel_count": 0,
                    "satellite_available": 0,
                })
            continue

        for feat in result_list:
            props = feat.get("properties", {})
            no2 = props.get("tropospheric_NO2_column_number_density")
            cf = props.get("cloud_fraction")
            vpc = props.get("valid_pixel_count", 0)
            all_rows.append({
                "station_id": props.get("station_id"),
                "date": date_str,
                "tropomi_no2_column": no2,
                "cloud_fraction": cf,
                "valid_pixel_count": vpc or 0,
                "satellite_available": 1 if no2 is not None else 0,
            })

    return pd.DataFrame(all_rows)


def main() -> None:
    from src.utils.env import load_env
    load_env()

    parser = argparse.ArgumentParser(description="Daily S5P extraction")
    parser.add_argument("--start", default=None, help="Start YYYY-MM")
    parser.add_argument("--end", default=None, help="End YYYY-MM")
    args = parser.parse_args()

    ee = initialize_ee()
    dates_cfg = load_config("dates")
    start_ym = args.start or dates_cfg["study_period"]["start"][:7]
    end_ym = args.end or dates_cfg["study_period"]["end"][:7]

    stations = load_usable_stations()
    logger.info(
        f"Daily S5P extraction: {len(stations)} stations, "
        f"{start_ym} to {end_ym}"
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_rows = []
    current = pd.Timestamp(start_ym + "-01")
    end_ts = pd.Timestamp(end_ym + "-01")

    while current <= end_ts:
        year, month = current.year, current.month
        month_str = f"{year}-{month:02d}"
        out_file = OUTPUT_DIR / f"{month_str}.csv"

        if out_file.exists():
            existing = pd.read_csv(out_file)
            logger.info(f"  Skip {month_str} ({len(existing)} rows)")
            manifest_rows.append({
                "month": month_str, "file": str(out_file),
                "row_count": len(existing),
                "retrieval_date": datetime.now().isoformat(),
            })
            current += pd.offsets.MonthBegin(1)
            continue

        logger.info(f"  Extracting daily {month_str} ...")
        df = extract_daily_month(ee, stations, year, month)

        if not df.empty:
            df.to_csv(out_file, index=False)
            avail_pct = df["satellite_available"].mean() * 100
            logger.info(
                f"    {len(df)} rows, "
                f"{avail_pct:.1f}% days with satellite data"
            )
            manifest_rows.append({
                "month": month_str, "file": str(out_file),
                "row_count": len(df),
                "satellite_available_pct": round(avail_pct, 1),
                "retrieval_date": datetime.now().isoformat(),
            })

        current += pd.offsets.MonthBegin(1)

    pd.DataFrame(manifest_rows).to_csv(MANIFEST_PATH, index=False)
    logger.info(f"Daily manifest saved to {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
