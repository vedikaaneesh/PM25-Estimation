"""Fetch station inventory from the OpenAQ API v3.

OpenAQ aggregates air quality data from multiple providers worldwide,
including CPCB stations in India. This is used for cross-source comparison
and deduplication with the XKDR station list.

API docs:  https://docs.openaq.org/
Get a key: https://explore.openaq.org/  (free)

Set OPENAQ_API_KEY environment variable. The key is passed in the
X-API-Key header.

Usage:
    python -m src.ingest.fetch_openaq_stations
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from src.utils.config import load_config
from src.utils.env import load_env
from src.utils.logging_config import setup_logging

load_env()

logger = setup_logging()

OPENAQ_BASE_URL = "https://api.openaq.org/v3"
# PM2.5 parameter ID in OpenAQ (confirmed from API docs example)
PM25_PARAMETER_ID = 2
# India ISO code
INDIA_ISO = "IN"
OUTPUT_PATH = Path("data/raw/stations_openaq.csv")

# Max 1000 results per page per OpenAQ docs
PAGE_LIMIT = 1000


def _get_api_key() -> str:
    """Get OpenAQ API key from environment variable."""
    key = os.environ.get("OPENAQ_API_KEY", "")
    if not key:
        logger.warning(
            "OPENAQ_API_KEY not set. Get one at https://explore.openaq.org/"
        )
    return key


def fetch_locations_page(
    api_key: str,
    bbox: str,
    page: int = 1,
    limit: int = PAGE_LIMIT,
) -> tuple[list[dict[str, Any]], int]:
    """Fetch one page of OpenAQ locations for PM2.5 in a bounding box.

    Args:
        api_key: OpenAQ API key.
        bbox: Bounding box string "min_lon,min_lat,max_lon,max_lat".
        page: Page number (1-indexed).
        limit: Results per page (max 1000).

    Returns:
        Tuple of (results list, total found count).
    """
    headers = {"X-API-Key": api_key}
    params = {
        "bbox": bbox,
        "parameters_id": PM25_PARAMETER_ID,
        "iso": INDIA_ISO,
        "limit": limit,
        "page": page,
        "order_by": "id",
        "sort_order": "asc",
    }
    resp = requests.get(
        f"{OPENAQ_BASE_URL}/locations",
        headers=headers,
        params=params,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [])
    found = data.get("meta", {}).get("found", 0)
    return results, found


def fetch_all_locations(
    api_key: str, bbox: str
) -> list[dict[str, Any]]:
    """Fetch all OpenAQ PM2.5 locations in a bounding box, paginated.

    Args:
        api_key: OpenAQ API key.
        bbox: Bounding box string "min_lon,min_lat,max_lon,max_lat".

    Returns:
        List of location dicts.
    """
    all_results: list[dict[str, Any]] = []
    page = 1

    while True:
        logger.info(f"Fetching OpenAQ locations page {page} ...")
        results, found = fetch_locations_page(api_key, bbox, page=page)

        if not results:
            break

        all_results.extend(results)
        logger.info(
            f"  Got {len(results)} stations "
            f"(total so far: {len(all_results)}/{found})"
        )

        if len(all_results) >= found or len(results) < PAGE_LIMIT:
            break

        page += 1
        # Be polite to the API
        time.sleep(1)

    return all_results


def standardize_locations(
    raw: list[dict[str, Any]],
) -> pd.DataFrame:
    """Convert raw OpenAQ location dicts to standardized schema.

    Args:
        raw: List of location dicts from the OpenAQ API.

    Returns:
        DataFrame with columns: source_id, source, name, locality,
        latitude, longitude, timezone, provider, is_monitor, is_mobile,
        instrument, first_date_utc, last_date_utc, parameters.
    """
    rows: list[dict[str, Any]] = []
    for loc in raw:
        coords = loc.get("coordinates") or {}
        dt_first = loc.get("datetimeFirst") or {}
        dt_last = loc.get("datetimeLast") or {}
        sensors = loc.get("sensors") or []
        instruments = loc.get("instruments") or []
        params = [s.get("parameter", {}).get("name", "") for s in sensors]
        inst_names = [i.get("name", "") for i in instruments]

        rows.append({
            "source_id": loc.get("id"),
            "source": "openaq",
            "name": loc.get("name", ""),
            "locality": loc.get("locality", ""),
            "latitude": coords.get("latitude"),
            "longitude": coords.get("longitude"),
            "timezone": loc.get("timezone", ""),
            "provider": loc.get("provider", {}).get("name", ""),
            "is_monitor": loc.get("isMonitor"),
            "is_mobile": loc.get("isMobile"),
            "instrument": "; ".join(inst_names) if inst_names else "",
            "first_date_utc": dt_first.get("utc", ""),
            "last_date_utc": dt_last.get("utc", ""),
            "parameters": "; ".join(params) if params else "",
        })

    return pd.DataFrame(rows)


def main() -> None:
    """Fetch OpenAQ PM2.5 stations for the study bbox and save to CSV."""
    api_key = _get_api_key()
    if not api_key:
        logger.error("Cannot proceed without OPENAQ_API_KEY.")
        return

    config = load_config("study_area")
    bb = config["bbox"]
    bbox_str = f"{bb['west']},{bb['south']},{bb['east']},{bb['north']}"

    raw = fetch_all_locations(api_key, bbox_str)
    logger.info(f"Total OpenAQ locations fetched: {len(raw)}")

    df = standardize_locations(raw)
    if df.empty:
        logger.error("No stations found.")
        return

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)
    logger.info(f"Saved {len(df)} stations to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
