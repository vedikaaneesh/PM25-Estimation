"""Compute PM2.5 data completeness per station, year, and season.

Fetches daily PM2.5 aggregates from the XKDR API and computes:
  - Per-year daily completeness (% of days with data)
  - Per-season daily completeness
  - Overall study-period completeness

Stations meeting the configured threshold (default >= 70% daily
completeness) are flagged as usable.

Usage:
    python -m src.ingest.completeness_audit
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
DEFAULT_API_KEY = os.environ.get("XKDR_API_KEY") or "aqi_demo_wbf92Qx21zX-Wa_Tg8Dx1nXe"
STATIONS_PATH = Path("data/interim/stations_merged.csv")
OUTPUT_PATH = Path("data/interim/completeness_audit.csv")


def get_season(month: int) -> str:
    """Map month number to season label.

    Seasons (South India):
      pre-monsoon: Mar-May
      southwest-monsoon: Jun-Sep
      northeast-monsoon: Oct-Dec
      post-monsoon: Jan-Feb
    """
    if month in (3, 4, 5):
        return "pre-monsoon"
    elif month in (6, 7, 8, 9):
        return "southwest-monsoon"
    elif month in (10, 11, 12):
        return "northeast-monsoon"
    else:
        return "post-monsoon"


def fetch_daily_pm25(
    station_ids: list[str],
    start: str,
    end: str,
    api_key: str = DEFAULT_API_KEY,
) -> pd.DataFrame:
    """Fetch daily PM2.5 aggregates for a list of stations from XKDR.

    Args:
        station_ids: List of XKDR station IDs.
        start: Start date YYYY-MM-DD (IST).
        end: End date YYYY-MM-DD (IST).
        api_key: XKDR API bearer token.

    Returns:
        DataFrame with daily PM2.5 data.
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    params: list[tuple[str, str]] = [
        ("parameter", "PM2.5"),
        ("start", start),
        ("end", end),
        ("agg", "daily"),
        ("format", "csv"),
    ]
    for sid in station_ids:
        params.append(("station", sid))

    logger.info(
        f"Fetching daily PM2.5 for {len(station_ids)} stations "
        f"({start} to {end}) ..."
    )
    resp = requests.get(
        f"{XKDR_BASE_URL}/measurements",
        headers=headers,
        params=params,
        timeout=120,
    )

    if resp.status_code != 200:
        logger.error(f"API error {resp.status_code}: {resp.text[:500]}")
        return pd.DataFrame()

    if not resp.text.strip():
        return pd.DataFrame()

    df = pd.read_csv(pd.io.common.StringIO(resp.text))

    # Normalize column names
    for col in df.columns:
        lower = col.lower()
        if "station" in lower and "id" in lower:
            df = df.rename(columns={col: "station_id"})
        elif lower in ("period_start", "date", "day", "time"):
            df = df.rename(columns={col: "date"})
        elif lower == "value" or lower == "mean":
            df = df.rename(columns={col: "pm25_mean"})
        elif lower == "count":
            df = df.rename(columns={col: "hourly_count"})

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if "pm25_mean" not in df.columns:
        # Try other possible names
        value_cols = [c for c in df.columns if "value" in c.lower()
                       or "mean" in c.lower()]
        if value_cols:
            df = df.rename(columns={value_cols[0]: "pm25_mean"})

    logger.info(f"  Retrieved {len(df)} daily records")
    return df


def compute_completeness(
    daily_df: pd.DataFrame,
    start: str,
    end: str,
) -> pd.DataFrame:
    """Compute per-station, per-year, per-season completeness.

    Args:
        daily_df: DataFrame with station_id, date, pm25_mean columns.
        start: Study period start date.
        end: Study period end date.

    Returns:
        DataFrame with one row per station-year-season with completeness %.
    """
    if daily_df.empty:
        return pd.DataFrame()

    daily_df = daily_df.copy()
    daily_df["year"] = daily_df["date"].dt.year
    daily_df["month"] = daily_df["date"].dt.month
    daily_df["season"] = daily_df["month"].apply(get_season)

    # Count valid days per station-year-season
    records: list[dict[str, Any]] = []
    for sid, sid_df in daily_df.groupby("station_id"):
        for year, year_df in sid_df.groupby("year"):
            year_start = pd.Timestamp(f"{year}-01-01")
            year_end = pd.Timestamp(f"{year}-12-31")
            total_days_year = (year_end - year_start).days + 1
            valid_days_year = year_df["date"].nunique()

            for season, season_df in year_df.groupby("season"):
                season_months = {
                    "pre-monsoon": [3, 4, 5],
                    "southwest-monsoon": [6, 7, 8, 9],
                    "northeast-monsoon": [10, 11, 12],
                    "post-monsoon": [1, 2],
                }
                total_season = sum(
                    pd.Timestamp(f"{year}-{m:02d}-01").days_in_month
                    for m in season_months[season]
                )
                valid_season = season_df["date"].nunique()
                records.append({
                    "station_id": sid,
                    "year": int(year),
                    "season": season,
                    "valid_days": valid_season,
                    "total_days": total_season,
                    "completeness_pct": round(
                        valid_season / total_season * 100, 1
                    ) if total_season > 0 else 0,
                })

    return pd.DataFrame(records)


def main() -> None:
    """Run completeness audit for all merged stations."""
    if not STATIONS_PATH.exists():
        logger.error(f"Merged stations not found: {STATIONS_PATH}")
        logger.error("Run merge_stations first.")
        return

    stations_df = pd.read_csv(STATIONS_PATH)
    config = load_config("dates")
    start = config["study_period"]["start"]
    end = config["study_period"]["end"]
    thresholds = load_config("thresholds")
    min_pct = thresholds["station_completeness"]["min_daily_pct"]

    # With demo key, only 2024 data is available
    demo_key = DEFAULT_API_KEY.startswith("aqi_demo")
    if demo_key:
        logger.warning(
            "Using demo key: limited to 2024 data only. "
            "Set XKDR_API_KEY for full 2021-2024 coverage."
        )
        start = "2024-01-01"
        end = "2024-12-31"

    # Only query XKDR station IDs (site_* or DS*); OpenAQ-only stations
    # need a separate completeness path via OpenAQ API.
    xkdr_mask = stations_df["station_id"].astype(str).str.match(r"^(site_|DS)")
    xkdr_stations = stations_df[xkdr_mask]
    n_openaq_only = len(stations_df) - len(xkdr_stations)
    if n_openaq_only > 0:
        logger.info(
            f"{n_openaq_only} OpenAQ-only stations will be checked "
            f"separately (not via XKDR API)."
        )

    all_daily: list[pd.DataFrame] = []

    # Fetch per state to stay within row limits
    for state in xkdr_stations["state"].unique():
        state_stations = xkdr_stations[xkdr_stations["state"] == state]
        sids = state_stations["station_id"].astype(str).tolist()
        if not sids:
            continue
        logger.info(f"\n--- {state}: {len(sids)} stations ---")

        # Fetch in batches of 20 stations to avoid row limits
        batch_size = 20
        for i in range(0, len(sids), batch_size):
            batch = sids[i:i + batch_size]
            daily_df = fetch_daily_pm25(batch, start, end)
            if not daily_df.empty:
                all_daily.append(daily_df)

    if not all_daily:
        logger.error("No daily data retrieved.")
        return

    combined = pd.concat(all_daily, ignore_index=True)
    logger.info(f"\nTotal daily records: {len(combined)}")

    # Compute completeness
    comp_df = compute_completeness(combined, start, end)
    if comp_df.empty:
        logger.error("Could not compute completeness.")
        return

    # Flag usable stations (meeting threshold for the full study period)
    # Overall per-station completeness across all years
    overall = comp_df.groupby("station_id")[
        ["valid_days", "total_days"]
    ].sum().reset_index()
    overall["completeness_pct"] = (
        overall["valid_days"] / overall["total_days"] * 100
    ).round(1)
    overall["meets_threshold"] = overall["completeness_pct"] >= min_pct

    # Per-station-per-year (for the seasonal table)
    annual = comp_df.groupby(["station_id", "year"])[
        ["valid_days", "total_days"]
    ].sum().reset_index()
    annual["completeness_pct"] = (
        annual["valid_days"] / annual["total_days"] * 100
    ).round(1)
    annual["meets_threshold"] = annual["completeness_pct"] >= min_pct

    # Save results
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    comp_df.to_csv(OUTPUT_PATH, index=False)
    annual.to_csv(
        Path("data/interim/completeness_annual.csv"), index=False
    )
    overall.to_csv(
        Path("data/interim/completeness_overall.csv"), index=False
    )
    logger.info(f"Saved completeness to {OUTPUT_PATH}")
    logger.info(f"Saved annual completeness to data/interim/completeness_annual.csv")
    logger.info(f"Saved overall completeness to data/interim/completeness_overall.csv")

    # Summary
    n_total = combined["station_id"].nunique() if "station_id" in combined else 0
    n_usable = overall[overall["meets_threshold"]]["station_id"].nunique()
    logger.info(f"\n{'='*50}")
    logger.info(f"Stations with data: {n_total}")
    logger.info(f"Stations meeting {min_pct}% overall completeness: {n_usable}")

    # Per-state breakdown
    if not overall.empty:
        stations_df = pd.read_csv(STATIONS_PATH)
        overall_merged = overall.merge(
            stations_df[["station_id", "state"]].astype({"station_id": str}),
            on="station_id",
            how="left",
        )
        state_summary = overall_merged.groupby("state").agg(
            total=("station_id", "count"),
            usable=("meets_threshold", "sum"),
        ).reset_index()
        logger.info(f"\nPer-state usable stations:\n{state_summary.to_string(index=False)}")
    logger.info(f"{'='*50}")


if __name__ == "__main__":
    main()
