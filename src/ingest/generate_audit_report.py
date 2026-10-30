"""Generate the station audit report: map, tables, and markdown.

Produces:
  - reports/figures/station_map.png  (station locations by state)
  - reports/tables/seasonal_completeness.csv
  - docs/station_audit.md

Usage:
    python -m src.ingest.generate_audit_report
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt
import pandas as pd

from src.utils.config import load_config
from src.utils.env import load_env
from src.utils.logging_config import setup_logging

load_env()

logger = setup_logging()

STATIONS_PATH = Path("data/interim/stations_merged.csv")
COMPLETENESS_PATH = Path("data/interim/completeness_audit.csv")
OVERALL_PATH = Path("data/interim/completeness_overall.csv")
ANNUAL_PATH = Path("data/interim/completeness_annual.csv")
FIGURE_PATH = Path("reports/figures/station_map.png")
TABLE_PATH = Path("reports/tables/seasonal_completeness.csv")
REPORT_PATH = Path("docs/station_audit.md")

STATE_COLORS: dict[str, str] = {
    "Kerala": "#2ca02c",
    "Karnataka": "#1f77b4",
    "Tamil Nadu": "#ff7f0e",
    "Andhra Pradesh": "#d62728",
    "Telangana": "#9467bd",
}


def generate_station_map(stations: pd.DataFrame) -> Path:
    """Plot station locations colored by state and save as PNG.

    Args:
        stations: Merged station DataFrame with latitude/longitude/state.

    Returns:
        Path to the saved figure.
    """
    fig, ax = plt.subplots(1, 1, figsize=(10, 12))
    ax.set_facecolor("#f0f0f0")

    for state, color in STATE_COLORS.items():
        subset = stations[
            (stations["state"] == state)
            & stations["latitude"].notna()
            & stations["longitude"].notna()
        ]
        if subset.empty:
            continue
        ax.scatter(
            subset["longitude"],
            subset["latitude"],
            c=color,
            label=f"{state} ({len(subset)})",
            alpha=0.7,
            edgecolors="black",
            linewidths=0.5,
            s=60,
            zorder=3,
        )

    ax.set_xlabel("Longitude", fontsize=12)
    ax.set_ylabel("Latitude", fontsize=12)
    ax.set_title("PM2.5 Monitoring Stations in South India", fontsize=14)
    ax.legend(fontsize=10, loc="lower right")
    ax.grid(True, alpha=0.3)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(73, 86)
    ax.set_ylim(7, 20)

    FIGURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURE_PATH, dpi=200, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"Station map saved to {FIGURE_PATH}")
    return FIGURE_PATH


def generate_seasonal_table(comp: pd.DataFrame) -> pd.DataFrame:
    """Create a seasonal completeness pivot table.

    Rows: station_id + state, Columns: season, Values: mean completeness %.

    Args:
        comp: Completeness DataFrame from completeness_audit.

    Returns:
        Pivoted DataFrame saved as CSV.
    """
    if comp.empty:
        return pd.DataFrame()

    # Average completeness across years per station per season
    pivot = comp.groupby(["station_id", "season"])[
        "completeness_pct"
    ].mean().reset_index()
    pivot = pivot.pivot(
        index="station_id", columns="season", values="completeness_pct"
    ).reset_index()
    pivot.columns.name = None

    TABLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    pivot.to_csv(TABLE_PATH, index=False)
    logger.info(f"Seasonal completeness table saved to {TABLE_PATH}")
    return pivot


def generate_report(
    stations: pd.DataFrame,
    comp: pd.DataFrame,
    overall: pd.DataFrame,
    annual: pd.DataFrame,
    thresholds: dict,
    study_period: str,
) -> Path:
    """Generate the station audit markdown report.

    Args:
        stations: Merged station DataFrame.
        comp: Per-season completeness DataFrame.
        annual: Per-year completeness DataFrame.
        thresholds: Thresholds config dict.
        study_period: Human-readable study period string.

    Returns:
        Path to the report markdown file.
    """
    today = date.today().isoformat()
    min_pct = thresholds["station_completeness"]["min_daily_pct"]

    # Counts
    n_total = len(stations)
    state_counts = stations["state"].value_counts().to_dict()
    source_counts = stations["source"].value_counts().to_dict()

    n_usable = 0
    if not overall.empty:
        n_usable = overall[overall["meets_threshold"]]["station_id"].nunique()

    # Per-state usable counts
    state_usable: dict[str, int] = {}
    if not overall.empty:
        overall_merged = overall.merge(
            stations[["station_id", "state"]].astype({"station_id": str}),
            on="station_id",
            how="left",
        )
        state_usable = overall_merged[overall_merged["meets_threshold"]][
            "state"
        ].value_counts().to_dict()

    # Kerala-only check
    kerala_stations = stations[stations["state"] == "Kerala"]
    n_kerala = len(kerala_stations)

    if not annual.empty:
        kerala_overall = overall[
            overall["station_id"].isin(kerala_stations["station_id"].astype(str))
        ]
        n_kerala_usable = kerala_overall[
            kerala_overall["meets_threshold"]
        ]["station_id"].nunique() if not kerala_overall.empty else 0
    else:
        n_kerala_usable = 0

    # Recommendation
    if n_kerala_usable < 15:
        recommendation = (
            "**Recommendation: Use South India as the study area** "
            f"with Kerala as the monsoon focus sub-region. "
            f"Kerala has only {n_kerala_usable} usable stations "
            f"(< 15 threshold). South India has {n_usable} usable stations."
        )
    else:
        recommendation = (
            f"Kerala alone has {n_kerala_usable} usable stations "
            f"(>= 15 threshold). Kerala-only may be sufficient."
        )

    # Build markdown
    md = f"""# Station Audit Report

**Generated:** {today}
**Study period:** {study_period}
**Completeness threshold:** ≥{min_pct}% daily completeness

## Summary

| Metric | Count |
|--------|-------|
| Total stations (all sources) | {n_total} |
| Stations meeting completeness threshold | {n_usable} |
| Kerala stations (total) | {n_kerala} |
| Kerala stations (usable) | {n_kerala_usable} |

## Stations per State

| State | Total Stations | Usable (XKDR, >= {min_pct}%) |
|-------|-------|-------|
"""
    for state, count in sorted(state_counts.items()):
        usable = state_usable.get(state, 0)
        md += f"| {state} | {count} | {usable} |\n"

    md += f"""
## Stations per Source

| Source | Count |
|--------|-------|
"""
    for source, count in sorted(source_counts.items()):
        md += f"| {source} | {count} |\n"

    md += f"""
## Scope Decision

{recommendation}

## Seasonal Completeness

See `reports/tables/seasonal_completeness.csv` for the full table.

## Station Map

See `reports/figures/station_map.png`.

## Limitations

- Completeness was checked for 79 XKDR stations (CPCB CAAQM + US Embassy)
  using the XKDR API with full 2021-2024 data access.
- 80 OpenAQ-only stations have NOT been checked for completeness yet.
  These require separate OpenAQ measurements API queries.
- State assignment for OpenAQ-only stations uses approximate bounding boxes,
  not official state boundaries. Some edge stations may be misassigned.

## Open Decisions

- [ ] Final study area (Kerala-only vs South India)
- [ ] Study period confirmation
- [ ] Deduplication rule approval
- [ ] Whether to include OpenAQ-only stations (possible low-cost sensors)
- [ ] Completeness threshold (proposed: >= 70% daily over full period)
"""

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(md, encoding="utf-8")
    logger.info(f"Audit report saved to {REPORT_PATH}")
    return REPORT_PATH


def main() -> None:
    """Generate station map, seasonal table, and audit report."""
    if not STATIONS_PATH.exists():
        logger.error(f"Merged stations not found: {STATIONS_PATH}")
        return

    stations = pd.read_csv(STATIONS_PATH)
    comp = pd.read_csv(COMPLETENESS_PATH) if COMPLETENESS_PATH.exists() else pd.DataFrame()
    overall = pd.read_csv(OVERALL_PATH) if OVERALL_PATH.exists() else pd.DataFrame()
    annual = pd.read_csv(ANNUAL_PATH) if ANNUAL_PATH.exists() else pd.DataFrame()

    thresholds = load_config("thresholds")
    dates = load_config("dates")
    study_period = f"{dates['study_period']['start']} to {dates['study_period']['end']}"

    generate_station_map(stations)
    generate_seasonal_table(comp)
    generate_report(stations, comp, overall, annual, thresholds, study_period)

    logger.info("\nAudit report generation complete.")


if __name__ == "__main__":
    main()
