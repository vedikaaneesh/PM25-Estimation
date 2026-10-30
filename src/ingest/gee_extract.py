"""GEE daily point extraction at station coordinates.

Extracts daily mean values within a spatial buffer around each station.
Chunked by month and resumable (skips existing output files).

Key design decisions:
- S5P OFFL L3 in GEE is already QA-filtered during L3 ingestion.
  No additional qa_value filtering is needed — there is no qa_value band
  in the GEE L3 collections. We simply compute mean of cloud_fraction
  as a proxy for cloud contamination and filter during Stage 4 cleaning.
- MAIAC AOD: AOD_QA == 0 is best quality. We filter on AOD_QA and
  also record valid pixel count via reduceRegion count reducer.
- ERA5 and CAMS: no QA filtering needed; reanalysis is spatially complete.
- All extractions are daily aggregates (mean over the month then
  stored as monthly summary). For Stage 4, daily resolution will be
  extracted in a targeted way for matched station-days.

Usage:
    # Test one dataset, one month
    python -m src.ingest.gee_extract --dataset s5p_no2 --start 2021-01 --end 2021-01

    # Full extraction
    python -m src.ingest.gee_extract --dataset s5p_no2
    python -m src.ingest.gee_extract --dataset maiac_aod
    python -m src.ingest.gee_extract --dataset era5_land
    python -m src.ingest.gee_extract --dataset era5_blh
    python -m src.ingest.gee_extract --dataset cams_aod
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.ingest.gee_auth import initialize_ee
from src.utils.config import load_config
from src.utils.logging_config import setup_logging

logger = setup_logging()

STATIONS_PATH = Path("data/interim/stations_merged.csv")
COMPLETENESS_PATH = Path("data/interim/completeness_overall.csv")
DATASETS_CONFIG = Path("configs/gee_datasets.yaml")
OUTPUT_DIR = Path("data/raw/gee_extracts")
MANIFEST_PATH = Path("data/raw/gee_extract_manifest.csv")


def load_dataset_config(dataset_name: str) -> dict[str, Any]:
    """Load configuration for a specific GEE dataset."""
    with open(DATASETS_CONFIG, "r", encoding="utf-8") as f:
        all_configs = yaml.safe_load(f)
    datasets = all_configs.get("datasets", {})
    if dataset_name not in datasets:
        raise KeyError(f"Dataset '{dataset_name}' not in {DATASETS_CONFIG}")
    return datasets[dataset_name]


def load_usable_stations() -> pd.DataFrame:
    """Load usable stations (meeting completeness threshold) with coordinates."""
    comp = pd.read_csv(COMPLETENESS_PATH)
    usable = comp[comp["meets_threshold"]]["station_id"].astype(str).tolist()
    merged = pd.read_csv(STATIONS_PATH)
    merged["station_id"] = merged["station_id"].astype(str)
    return merged[
        merged["station_id"].isin(usable)
        & merged["latitude"].notna()
        & merged["longitude"].notna()
    ].copy()


def get_pixel_scale(collection_id: str) -> int:
    """Return appropriate pixel scale in metres for reduceRegion."""
    if "MCD19" in collection_id or "MAIAC" in collection_id:
        return 1000   # MAIAC: 1 km
    if "S5P" in collection_id or "COPERNICUS" in collection_id:
        return 1113   # ~0.01 arc deg at equator
    if "ERA5_LAND" in collection_id:
        return 11132  # ~0.1 deg
    if "ERA5" in collection_id:
        return 27830  # ~0.25 deg
    if "CAMS" in collection_id:
        return 44528  # ~0.4 deg
    return 5000


def extract_month(
    ee: Any,
    dataset_cfg: dict[str, Any],
    stations: pd.DataFrame,
    year: int,
    month: int,
    buffer_m: int = 5000,
) -> pd.DataFrame:
    """Extract monthly-mean values at all stations in a single GEE call.

    Uses ee.Image.reduceRegions() to extract values for all station buffers
    at once — much faster than per-station loops.

    Args:
        ee: Initialized ee module.
        dataset_cfg: Dataset configuration dict.
        stations: DataFrame with station_id, latitude, longitude.
        year: Year.
        month: Month.
        buffer_m: Buffer radius in metres around each station.

    Returns:
        DataFrame with one row per station, monthly mean values.
    """
    collection_id = dataset_cfg["collection"]
    bands_cfg = dataset_cfg["bands"]
    scale_factor = dataset_cfg.get("scale", 1.0)
    is_maiac = "MCD19" in collection_id

    start = ee.Date.fromYMD(year, month, 1)
    end = start.advance(1, "month")

    raw_band_names = [b["name"] for b in bands_cfg]

    collection = (
        ee.ImageCollection(collection_id)
        .filterDate(start, end)
        .select(raw_band_names)
    )

    # MAIAC: mask pixels where AOD_QA != 0 before averaging
    if is_maiac:
        def _mask_aod(img):
            qa = img.select("AOD_QA")
            mask = qa.eq(0)
            return img.updateMask(mask)
        collection_qa = (
            ee.ImageCollection(collection_id)
            .filterDate(start, end)
            .select(raw_band_names + ["AOD_QA"])
        )
        collection = collection_qa.map(_mask_aod).select(raw_band_names)

    # Monthly mean composite
    monthly_img = collection.mean()

    # Add valid-pixel count as an extra band
    count_img = collection.select(raw_band_names[0]).count().rename("valid_pixel_count")
    monthly_img = monthly_img.addBands(count_img)

    px_scale = get_pixel_scale(collection_id)

    # Build a FeatureCollection of buffered station points
    features = []
    for _, row in stations.iterrows():
        pt = ee.Geometry.Point([float(row["longitude"]), float(row["latitude"])])
        feat = ee.Feature(pt.buffer(buffer_m), {"station_id": str(row["station_id"])})
        features.append(feat)
    fc = ee.FeatureCollection(features)

    # Extract all stations in one call
    try:
        result_fc = monthly_img.reduceRegions(
            collection=fc,
            reducer=ee.Reducer.mean(),
            scale=px_scale,
        )
        result_list = result_fc.getInfo()["features"]
    except Exception as exc:
        logger.error(f"  reduceRegions failed for {year}-{month:02d}: {exc}")
        return pd.DataFrame()

    results = []
    for feat in result_list:
        props = feat.get("properties", {})
        row: dict[str, Any] = {
            "station_id": props.get("station_id"),
            "year": year,
            "month": month,
            "buffer_m": buffer_m,
            "valid_pixel_count": props.get("valid_pixel_count", 0),
        }
        for band_cfg in bands_cfg:
            raw_val = props.get(band_cfg["name"])
            row[band_cfg["output"]] = (
                raw_val * scale_factor if raw_val is not None else None
            )
        results.append(row)

    return pd.DataFrame(results)


def main() -> None:
    """Run GEE extraction for a specified dataset, monthly chunks."""
    parser = argparse.ArgumentParser(description="GEE point extraction")
    parser.add_argument("--dataset", required=True,
                        help="Dataset name from configs/gee_datasets.yaml")
    parser.add_argument("--buffer", type=int, default=5000,
                        help="Buffer radius in metres (default 5000 = 5 km)")
    parser.add_argument("--start", default=None, help="Start YYYY-MM")
    parser.add_argument("--end", default=None, help="End YYYY-MM")
    args = parser.parse_args()

    ee = initialize_ee()
    dataset_cfg = load_dataset_config(args.dataset)
    dates_cfg = load_config("dates")

    start_ym = args.start or dates_cfg["study_period"]["start"][:7]
    end_ym = args.end or dates_cfg["study_period"]["end"][:7]

    stations = load_usable_stations()
    logger.info(
        f"Extracting {args.dataset}: {len(stations)} stations, "
        f"buffer={args.buffer}m, {start_ym} to {end_ym}"
    )

    output_subdir = OUTPUT_DIR / args.dataset
    output_subdir.mkdir(parents=True, exist_ok=True)

    manifest_rows = []
    current = pd.Timestamp(start_ym + "-01")
    end_ts = pd.Timestamp(end_ym + "-01")

    while current <= end_ts:
        year, month = current.year, current.month
        month_str = f"{year}-{month:02d}"
        out_file = output_subdir / f"{month_str}.csv"

        # Resumable
        if out_file.exists():
            existing = pd.read_csv(out_file)
            logger.info(f"  Skip {month_str} (already extracted, "
                        f"{len(existing)} rows)")
            manifest_rows.append({
                "dataset": args.dataset,
                "month": month_str,
                "file": str(out_file),
                "row_count": len(existing),
                "buffer_m": args.buffer,
                "retrieval_date": datetime.now().isoformat(),
            })
            current += pd.offsets.MonthBegin(1)
            continue

        logger.info(f"  Extracting {month_str} ...")
        df = extract_month(ee, dataset_cfg, stations, year, month, args.buffer)

        if not df.empty:
            df.to_csv(out_file, index=False)
            n_valid = df[[c["output"] for c in dataset_cfg["bands"]]].notna().any(axis=1).sum()
            logger.info(f"    {len(df)} stations, {n_valid} with valid data -> {out_file.name}")
            manifest_rows.append({
                "dataset": args.dataset,
                "month": month_str,
                "file": str(out_file),
                "row_count": len(df),
                "buffer_m": args.buffer,
                "retrieval_date": datetime.now().isoformat(),
            })
        else:
            logger.warning(f"    No data for {month_str}")

        current += pd.offsets.MonthBegin(1)

    manifest = pd.DataFrame(manifest_rows)
    manifest.to_csv(MANIFEST_PATH, index=False)
    logger.info(f"\nManifest: {len(manifest)} months -> {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
