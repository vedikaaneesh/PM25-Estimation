"""Merge station inventories from multiple sources and deduplicate.

Combines XKDR (CPCB CAAQM) and OpenAQ station lists into a unified
inventory. Deduplicates by coordinate proximity and name similarity.
Assigns Indian state based on approximate state bounding boxes when
the source does not provide it directly.

Usage:
    python -m src.ingest.merge_stations
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.utils.config import load_config
from src.utils.logging_config import setup_logging

logger = setup_logging()

XKDR_PATH = Path("data/raw/stations_xkdr.csv")
OPENAQ_PATH = Path("data/raw/stations_openaq.csv")
OUTPUT_PATH = Path("data/interim/stations_merged.csv")
DEDUP_LOG_PATH = Path("data/interim/dedup_log.csv")

# Approximate state bounding boxes [west, south, east, north]
# Overlap at edges; coordinate matching to XKDR takes precedence.
STATE_BBOXES: dict[str, list[float]] = {
    "Kerala": [74.0, 8.0, 78.0, 13.0],
    "Karnataka": [74.0, 11.0, 78.5, 18.5],
    "Tamil Nadu": [76.0, 8.0, 80.5, 13.5],
    "Andhra Pradesh": [76.0, 13.0, 85.0, 19.5],
    "Telangana": [77.0, 16.0, 82.0, 19.5],
}


def assign_state_by_coords(
    lat: float | None, lon: float | None
) -> str:
    """Assign a state name based on approximate bounding boxes.

    Args:
        lat: Latitude.
        lon: Longitude.

    Returns:
        State name, or "Unknown" if no match.
    """
    if lat is None or lon is None or np.isnan(lat) or np.isnan(lon):
        return "Unknown"
    for state, bbox in STATE_BBOXES.items():
        if bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]:
            return state
    return "Unknown"


def load_xkdr() -> pd.DataFrame:
    """Load XKDR station CSV, handling column name variations."""
    if not XKDR_PATH.exists():
        logger.warning(f"XKDR stations not found at {XKDR_PATH}")
        return pd.DataFrame()
    df = pd.read_csv(XKDR_PATH)

    # Normalize column names (XKDR may use state_name or state)
    if "state_name" not in df.columns and "state" in df.columns:
        df = df.rename(columns={"state": "state_name"})

    # Standardize column names
    rename_map: dict[str, str] = {}
    for col in df.columns:
        lower = col.lower()
        if lower in ("station_id", "site_id", "id"):
            rename_map[col] = "station_id"
        elif lower in ("station_name", "name", "site_name"):
            rename_map[col] = "station_name"
        elif lower in ("state_name", "state"):
            rename_map[col] = "state"
        elif lower in ("city_name", "city", "locality"):
            rename_map[col] = "city"
        elif lower == "latitude":
            rename_map[col] = "latitude"
        elif lower == "longitude":
            rename_map[col] = "longitude"
        elif lower in ("source", "data_source"):
            rename_map[col] = "source"
        elif lower in ("first_reading", "first_date", "datetimefirst"):
            rename_map[col] = "first_date"
        elif lower in ("last_reading", "last_date", "datetimelast"):
            rename_map[col] = "last_date"
    df = df.rename(columns=rename_map)
    df["source"] = df.get("source", pd.Series(["xkdr"] * len(df)))

    logger.info(f"Loaded {len(df)} XKDR stations")
    return df


def load_openaq() -> pd.DataFrame:
    """Load OpenAQ station CSV."""
    if not OPENAQ_PATH.exists():
        logger.warning(f"OpenAQ stations not found at {OPENAQ_PATH}")
        return pd.DataFrame()
    df = pd.read_csv(OPENAQ_PATH)

    # Assign state by coordinates since OpenAQ doesn't provide it
    df["state"] = df.apply(
        lambda r: assign_state_by_coords(r.get("latitude"),
                                          r.get("longitude")),
        axis=1,
    )
    logger.info(f"Loaded {len(df)} OpenAQ stations")
    return df


def merge_and_deduplicate(
    xkdr_df: pd.DataFrame, openaq_df: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Merge station lists and deduplicate by coordinate proximity.

    Deduplication rule: two stations from different sources are the same
    if their coordinates are within coordinate_tolerance_deg (default 0.005,
    ~500 m) of each other. Keep the XKDR record as primary and note the
    OpenAQ match in the source column.

    Args:
        xkdr_df: XKDR station DataFrame.
        openaq_df: OpenAQ station DataFrame.

    Returns:
        Tuple of (merged DataFrame, dedup log DataFrame).
    """
    thresholds = load_config("thresholds")
    tol = thresholds["dedup"]["coordinate_tolerance_deg"]

    # Ensure we have the essential columns
    essential = ["station_id", "station_name", "state", "city",
                 "latitude", "longitude", "source"]

    # Start with XKDR as the primary list
    if xkdr_df.empty and openaq_df.empty:
        return pd.DataFrame(columns=essential), pd.DataFrame()

    merged_rows: list[dict[str, Any]] = []
    dedup_log: list[dict[str, Any]] = []

    # Add XKDR stations
    if not xkdr_df.empty:
        for _, row in xkdr_df.iterrows():
            merged_rows.append({
                "station_id": row.get("station_id", ""),
                "station_name": row.get("station_name", ""),
                "state": row.get("state", "Unknown"),
                "city": row.get("city", ""),
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "source": "xkdr",
                "first_date": row.get("first_date", ""),
                "last_date": row.get("last_date", ""),
                "provider": "",
                "is_monitor": True,
            })

    # Add OpenAQ stations, checking for duplicates
    if not openaq_df.empty:
        existing_coords = np.array([
            [r["latitude"], r["longitude"]]
            for r in merged_rows
            if r["latitude"] is not None and r["longitude"] is not None
        ])

        for _, row in openaq_df.iterrows():
            lat = row.get("latitude")
            lon = row.get("longitude")

            is_dup = False
            if lat is not None and lon is not None and len(existing_coords) > 0:
                dists = np.sqrt(
                    (existing_coords[:, 0] - lat) ** 2
                    + (existing_coords[:, 1] - lon) ** 2
                )
                min_dist = np.min(dists)
                if min_dist < tol:
                    is_dup = True
                    matched_idx = int(np.argmin(dists))
                    dedup_log.append({
                        "openaq_id": row.get("source_id", ""),
                        "openaq_name": row.get("name", ""),
                        "matched_xkdr_id": merged_rows[matched_idx].get("station_id", ""),
                        "matched_xkdr_name": merged_rows[matched_idx].get("station_name", ""),
                        "coordinate_distance_deg": round(min_dist, 6),
                        "rule": "coordinate_match",
                    })
                    # Update source to show cross-source presence
                    merged_rows[matched_idx]["source"] = "xkdr+openaq"

            if not is_dup:
                merged_rows.append({
                    "station_id": str(row.get("source_id", "")),
                    "station_name": row.get("name", ""),
                    "state": row.get("state", "Unknown"),
                    "city": row.get("locality", ""),
                    "latitude": lat,
                    "longitude": lon,
                    "source": "openaq",
                    "first_date": row.get("first_date_utc", ""),
                    "last_date": row.get("last_date_utc", ""),
                    "provider": row.get("provider", ""),
                    "is_monitor": row.get("is_monitor", True),
                })

    merged_df = pd.DataFrame(merged_rows)
    dedup_df = pd.DataFrame(dedup_log)

    logger.info(
        f"Merged: {len(merged_df)} stations "
        f"({(merged_df['source'] == 'xkdr').sum()} xkdr-only, "
        f"{(merged_df['source'] == 'openaq').sum()} openaq-only, "
        f"{(merged_df['source'] == 'xkdr+openaq').sum()} both)"
    )
    return merged_df, dedup_df


def main() -> None:
    """Load both sources, merge, deduplicate, and save."""
    xkdr_df = load_xkdr()
    openaq_df = load_openaq()

    merged_df, dedup_df = merge_and_deduplicate(xkdr_df, openaq_df)

    if merged_df.empty:
        logger.error("No stations to merge.")
        return

    # Filter to study states only
    study_states = load_config("study_area")["states"]
    merged_df = merged_df[merged_df["state"].isin(study_states)]
    logger.info(f"After filtering to study states: {len(merged_df)} stations")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    merged_df.to_csv(OUTPUT_PATH, index=False)
    logger.info(f"Saved merged stations to {OUTPUT_PATH}")

    if not dedup_df.empty:
        DEDUP_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        dedup_df.to_csv(DEDUP_LOG_PATH, index=False)
        logger.info(
            f"Saved {len(dedup_df)} deduplication records to {DEDUP_LOG_PATH}"
        )

    # Summary by state
    logger.info("\nStations per state:\n" +
                merged_df["state"].value_counts().to_string())
    logger.info("\nStations per source:\n" +
                merged_df["source"].value_counts().to_string())


if __name__ == "__main__":
    main()
