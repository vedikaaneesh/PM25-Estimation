"""Fetch station inventory from the XKDR India Air Quality API.

XKDR provides cleaned CPCB CAAQM data for India. The /v1/stations endpoint
returns station metadata including coordinates, first/last reading dates,
and pollutants measured.

API docs:  https://airquality.xkdr.org/
Get a key: https://airquality.xkdr.org/signup  (free, no rate limits)

The demo key (aqi_demo_wbf92Qx21zX-Wa_Tg8Dx1nXe) is capped at 10K rows
and 2024 data only. Set XKDR_API_KEY environment variable for full access.

Usage:
    python -m src.ingest.fetch_xkdr_stations
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from src.utils.config import load_config
from src.utils.env import load_env
from src.utils.logging_config import setup_logging

load_env()

logger = setup_logging()

XKDR_BASE_URL = "https://airquality.xkdr.org/v1"
# Demo key: 10K rows/query, 2024 data only.
# Set XKDR_API_KEY env var for unlimited access.
DEFAULT_API_KEY = os.environ.get("XKDR_API_KEY") or "aqi_demo_wbf92Qx21zX-Wa_Tg8Dx1nXe"
OUTPUT_PATH = Path("data/raw/stations_xkdr.csv")
STUDY_STATES = [
    "Kerala", "Karnataka", "Tamil Nadu", "TamilNadu",
    "Andhra Pradesh", "Telangana", "Puducherry",
]
# Normalize state name aliases
STATE_ALIASES = {
    "TamilNadu": "Tamil Nadu",
    "Pondicherry": "Puducherry",
}


def fetch_stations_for_state(
    state: str, api_key: str = DEFAULT_API_KEY
) -> list[dict[str, Any]]:
    """Fetch all stations for a given state from XKDR API.

    Args:
        state: Indian state name (case-insensitive exact match).
        api_key: XKDR API bearer token.

    Returns:
        List of station dicts as returned by the API.
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {"state": state, "format": "json"}
    logger.info(f"Fetching stations for state={state} ...")
    resp = requests.get(
        f"{XKDR_BASE_URL}/stations",
        headers=headers,
        params=params,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    # XKDR returns {"meta": {...}, "data": [...]}
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    logger.warning(f"Unexpected XKDR response structure for {state}")
    return [data] if data else []


def fetch_all_stations(
    api_key: str = DEFAULT_API_KEY,
) -> pd.DataFrame:
    """Fetch stations for all study states and return a DataFrame.

    Args:
        api_key: XKDR API bearer token.

    Returns:
        DataFrame with one row per station.
    """
    all_stations: list[dict[str, Any]] = []
    for state in STUDY_STATES:
        try:
            stations = fetch_stations_for_state(state, api_key)
            # Normalize state name
            canonical = STATE_ALIASES.get(state, state)
            for s in stations:
                s["state_name"] = canonical
            logger.info(f"  {state}: {len(stations)} stations")
            all_stations.extend(stations)
        except requests.HTTPError as e:
            logger.error(f"Failed to fetch {state}: {e}")

    if not all_stations:
        logger.error("No stations fetched from XKDR API.")
        return pd.DataFrame()

    df = pd.DataFrame(all_stations)
    logger.info(f"Total XKDR stations: {len(df)}")
    return df


def main() -> None:
    """Fetch XKDR stations for study states and save to CSV."""
    df = fetch_all_stations()
    if df.empty:
        logger.error("No data retrieved. Exiting.")
        return

    # Ensure output directory exists
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)
    logger.info(f"Saved {len(df)} stations to {OUTPUT_PATH}")

    # Quick summary
    if "state_name" in df.columns:
        state_col = "state_name"
    elif "state" in df.columns:
        state_col = "state"
    else:
        state_col = None

    if state_col:
        logger.info("\n" + df[state_col].value_counts().to_string())


if __name__ == "__main__":
    main()
