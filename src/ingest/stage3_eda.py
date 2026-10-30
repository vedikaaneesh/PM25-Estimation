"""Stage 3: Exploratory Data Analysis.

Produces:
  reports/figures/missingness_by_variable.png
  reports/figures/missingness_satellite_monthly.png
  reports/figures/pm25_seasonality.png
  reports/figures/pm25_distribution.png
  reports/figures/pm25_station_correlation.png
  reports/figures/pm25_correlation_vs_distance.png
  reports/tables/missingness_table.csv
  reports/tables/pm25_seasonal_stats.csv
  reports/tables/satellite_availability.csv

Usage:
    python -m src.ingest.stage3_eda
"""
from __future__ import annotations

import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

from src.utils.config import load_config
from src.utils.env import load_env
from src.utils.gee_loader import load_all_gee
from src.utils.logging_config import setup_logging
from src.utils.seasons import SEASON_MAP, SEASON_ORDER, add_temporal_columns

load_env()
logger = setup_logging()

FIGURES_DIR = Path("reports/figures")
TABLES_DIR = Path("reports/tables")
PM25_DIR = Path("data/raw/pm25_hourly")
STATIONS_PATH = Path("data/interim/stations_merged.csv")

SEASON_COLORS = {
    "post-monsoon": "#1f77b4",
    "pre-monsoon": "#ff7f0e",
    "southwest-monsoon": "#2ca02c",
    "northeast-monsoon": "#d62728",
}


def load_pm25_daily() -> pd.DataFrame:
    """Load all PM2.5 hourly files and aggregate to daily mean."""
    logger.info("Loading PM2.5 hourly data ...")
    dfs = []
    for f in sorted(PM25_DIR.glob("*.csv")):
        df = pd.read_csv(f, parse_dates=["timestamp_ist"])
        df["date"] = df["timestamp_ist"].dt.normalize()
        daily = (
            df.groupby(["station_id", "date"])["pm25"]
            .agg(["mean", "count"])
            .reset_index()
        )
        daily.columns = ["station_id", "date", "pm25_daily", "hourly_count"]
        # Require at least 18 of 24 hours for a valid daily value
        daily = daily[daily["hourly_count"] >= 18].copy()
        daily = daily.drop(columns="hourly_count")
        dfs.append(daily)

    combined = pd.concat(dfs, ignore_index=True)
    combined = add_temporal_columns(combined, "date")
    logger.info(f"  PM2.5 daily: {len(combined):,} station-days across "
                f"{combined['station_id'].nunique()} stations")
    return combined


def plot_missingness_by_variable(gee_data: dict) -> None:
    """Bar chart of data availability (% months with data) per GEE variable."""
    labels, availability = [], []
    for name, df in sorted(gee_data.items()):
        if df.empty:
            labels.append(name)
            availability.append(0)
            continue
        value_cols = [c for c in df.columns
                      if c not in ("station_id", "year", "month",
                                   "buffer_m", "valid_pixel_count")]
        if not value_cols:
            continue
        pct = df[value_cols[0]].notna().mean() * 100
        labels.append(name)
        availability.append(pct)

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.barh(labels, availability, color="#2196F3", edgecolor="white")
    ax.axvline(70, color="red", linestyle="--", linewidth=1, label="70% threshold")
    ax.set_xlabel("% station-months with valid data")
    ax.set_title("GEE Dataset Availability (2021–2024)")
    ax.set_xlim(0, 105)
    ax.legend()
    for bar, val in zip(bars, availability):
        ax.text(val + 0.5, bar.get_y() + bar.get_height() / 2,
                f"{val:.0f}%", va="center", fontsize=9)
    plt.tight_layout()
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES_DIR / "missingness_by_variable.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved missingness_by_variable.png")


def plot_satellite_monthly_availability(gee_data: dict) -> pd.DataFrame:
    """Heatmap of monthly S5P NO2 availability by month, averaged across stations."""
    if "s5p_no2" not in gee_data or gee_data["s5p_no2"].empty:
        logger.warning("s5p_no2 not available for monthly plot")
        return pd.DataFrame()

    df = gee_data["s5p_no2"].copy()
    df["month_label"] = df["month"].map({
        1:"Jan",2:"Feb",3:"Mar",4:"Apr",5:"May",6:"Jun",
        7:"Jul",8:"Aug",9:"Sep",10:"Oct",11:"Nov",12:"Dec"
    })
    # Availability: % of stations with non-null NO2 per year-month
    avail = (
        df.groupby(["year", "month"])["tropomi_no2_column"]
        .apply(lambda x: x.notna().mean() * 100)
        .reset_index()
        .rename(columns={"tropomi_no2_column": "availability_pct"})
    )

    pivot = avail.pivot(index="year", columns="month", values="availability_pct")

    fig, ax = plt.subplots(figsize=(12, 4))
    im = ax.imshow(pivot.values, aspect="auto", cmap="RdYlGn", vmin=0, vmax=100)
    ax.set_xticks(range(12))
    ax.set_xticklabels(["Jan","Feb","Mar","Apr","May","Jun",
                        "Jul","Aug","Sep","Oct","Nov","Dec"])
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index.astype(str))
    plt.colorbar(im, ax=ax, label="% stations with valid NO2")
    ax.set_title("TROPOMI NO2 Availability by Month (all stations)")

    # Highlight monsoon months
    for m in [6, 7, 8, 9]:
        ax.axvline(m - 1 - 0.5, color="blue", linewidth=0.5, alpha=0.5)
        ax.axvline(m - 1 + 0.5, color="blue", linewidth=0.5, alpha=0.5)

    plt.tight_layout()
    fig.savefig(FIGURES_DIR / "missingness_satellite_monthly.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved missingness_satellite_monthly.png")

    # Save table
    avail.to_csv(TABLES_DIR / "satellite_availability.csv", index=False)
    return avail


def plot_pm25_seasonality(pm25: pd.DataFrame, stations: pd.DataFrame) -> None:
    """Box plots of PM2.5 by season, split by state."""
    merged = pm25.merge(
        stations[["station_id", "state"]].astype({"station_id": str}),
        on="station_id",
        how="left",
    )

    states = sorted(merged["state"].dropna().unique())
    fig, axes = plt.subplots(1, len(states), figsize=(4 * len(states), 5), sharey=True)

    for ax, state in zip(axes, states):
        state_df = merged[merged["state"] == state]
        data_by_season = [
            state_df[state_df["season"] == s]["pm25_daily"].dropna().values
            for s in SEASON_ORDER
        ]
        bp = ax.boxplot(
            data_by_season,
            tick_labels=[s.replace("-", "\n") for s in SEASON_ORDER],
            patch_artist=True,
            medianprops={"color": "black", "linewidth": 2},
            flierprops={"marker": ".", "markersize": 2, "alpha": 0.3},
        )
        for patch, season in zip(bp["boxes"], SEASON_ORDER):
            patch.set_facecolor(SEASON_COLORS[season])
        ax.set_title(state, fontsize=10)
        ax.set_xlabel("")
        ax.tick_params(axis="x", labelsize=7)

    axes[0].set_ylabel("PM2.5 (µg/m³)")
    fig.suptitle("PM2.5 Seasonality by State (2021–2024)", fontsize=13, y=1.02)
    # WHO 24h guideline (15 µg/m³) and India NAAQS 24h (60 µg/m³)
    for ax in axes:
        ax.axhline(15, color="green", linestyle="--", linewidth=1, alpha=0.8)
        ax.axhline(60, color="red", linestyle="--", linewidth=1, alpha=0.8)
    # Legend on first axis only
    axes[0].plot([], [], "g--", linewidth=1, label="WHO 24h (15)")
    axes[0].plot([], [], "r--", linewidth=1, label="NAAQS 24h (60)")
    axes[0].legend(fontsize=7, loc="upper right")
    plt.tight_layout()
    fig.savefig(FIGURES_DIR / "pm25_seasonality.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved pm25_seasonality.png")


def plot_pm25_distribution(pm25: pd.DataFrame) -> None:
    """Histogram of PM2.5 daily values, overall and by season."""
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))

    # Overall
    ax = axes[0]
    vals = pm25["pm25_daily"].dropna()
    ax.hist(vals.clip(0, 200), bins=80, color="#1f77b4", edgecolor="white")
    ax.axvline(vals.median(), color="red", linestyle="--",
               label=f"Median: {vals.median():.1f}")
    ax.axvline(15, color="green", linestyle=":", linewidth=1.5,
               label="WHO 24h (15 µg/m³)")
    ax.axvline(60, color="orange", linestyle=":", linewidth=1.5,
               label="NAAQS 24h (60 µg/m³)")
    ax.set_xlabel("PM2.5 (µg/m³)")
    ax.set_ylabel("Count")
    ax.set_title("PM2.5 Distribution (all stations, 2021–2024)")
    ax.legend(fontsize=8)

    # By season
    ax = axes[1]
    for season in SEASON_ORDER:
        s_vals = pm25[pm25["season"] == season]["pm25_daily"].dropna()
        ax.hist(s_vals.clip(0, 200), bins=60, alpha=0.6,
                color=SEASON_COLORS[season], label=season, edgecolor="none")
    ax.set_xlabel("PM2.5 (µg/m³)")
    ax.set_title("PM2.5 by Season")
    ax.legend(fontsize=8)

    plt.tight_layout()
    fig.savefig(FIGURES_DIR / "pm25_distribution.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved pm25_distribution.png")


def compute_seasonal_stats(pm25: pd.DataFrame) -> pd.DataFrame:
    """Compute per-state per-season PM2.5 statistics."""
    stations = pd.read_csv(STATIONS_PATH)
    merged = pm25.merge(
        stations[["station_id", "state"]].astype({"station_id": str}),
        on="station_id", how="left",
    )
    stats = (
        merged.groupby(["state", "season"])["pm25_daily"]
        .agg(mean="mean", median="median", std="std",
             p25=lambda x: x.quantile(0.25),
             p75=lambda x: x.quantile(0.75),
             n="count")
        .round(2)
        .reset_index()
    )
    stats.to_csv(TABLES_DIR / "pm25_seasonal_stats.csv", index=False)
    return stats


def compute_station_correlations(pm25: pd.DataFrame) -> pd.DataFrame:
    """Compute pairwise PM2.5 correlations between stations."""
    pivot = pm25.pivot_table(
        index="date", columns="station_id", values="pm25_daily"
    )
    corr = pivot.corr(min_periods=60)
    return corr


def plot_correlation_vs_distance(pm25: pd.DataFrame, stations: pd.DataFrame) -> None:
    """Scatter: pairwise PM2.5 correlation vs station-pair distance."""
    from itertools import combinations

    corr = compute_station_correlations(pm25)
    stations_idx = stations.set_index("station_id")

    distances, correlations = [], []
    station_list = [s for s in corr.columns if s in stations_idx.index]

    for s1, s2 in combinations(station_list, 2):
        r = corr.loc[s1, s2]
        if pd.isna(r):
            continue
        lat1 = stations_idx.loc[s1, "latitude"]
        lon1 = stations_idx.loc[s1, "longitude"]
        lat2 = stations_idx.loc[s2, "latitude"]
        lon2 = stations_idx.loc[s2, "longitude"]
        if any(pd.isna([lat1, lon1, lat2, lon2])):
            continue
        # Approximate distance in km (Haversine simplified)
        dlat = np.radians(lat2 - lat1)
        dlon = np.radians(lon2 - lon1)
        a = np.sin(dlat/2)**2 + np.cos(np.radians(lat1)) * \
            np.cos(np.radians(lat2)) * np.sin(dlon/2)**2
        dist_km = 2 * 6371 * np.arcsin(np.sqrt(a))
        distances.append(dist_km)
        correlations.append(r)

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(distances, correlations, alpha=0.15, s=8, color="#1f77b4")
    # Trend line
    if len(distances) > 10:
        z = np.polyfit(distances, correlations, 1)
        p = np.poly1d(z)
        xs = np.linspace(min(distances), max(distances), 200)
        ax.plot(xs, p(xs), "r-", linewidth=1.5, label="Trend")
    ax.axhline(0, color="gray", linewidth=0.5)
    ax.set_xlabel("Distance between stations (km)")
    ax.set_ylabel("Pearson r (daily PM2.5)")
    ax.set_title("Station PM2.5 Correlation vs Distance")
    ax.legend()
    plt.tight_layout()
    fig.savefig(FIGURES_DIR / "pm25_correlation_vs_distance.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved pm25_correlation_vs_distance.png")


def build_missingness_table(pm25: pd.DataFrame, gee_data: dict) -> pd.DataFrame:
    """Build comprehensive missingness table by variable, month, and season."""
    rows = []

    # PM2.5 ground (station-days with valid daily value / total possible)
    total_station_days = pm25.groupby("station_id")["date"].count()
    pm25_availability = pm25["pm25_daily"].notna().mean() * 100
    rows.append({
        "variable": "pm25_ground",
        "source": "XKDR/CPCB",
        "overall_pct": round(pm25_availability, 1),
        "sw_monsoon_pct": round(
            pm25[pm25["season"] == "southwest-monsoon"]["pm25_daily"]
            .notna().mean() * 100, 1
        ),
        "post_monsoon_pct": round(
            pm25[pm25["season"] == "post-monsoon"]["pm25_daily"]
            .notna().mean() * 100, 1
        ),
    })

    for name, df in sorted(gee_data.items()):
        if df.empty:
            continue
        val_cols = [c for c in df.columns
                    if c not in ("station_id", "year", "month",
                                 "buffer_m", "valid_pixel_count")]
        if not val_cols:
            continue

        df2 = df.copy()
        df2["season"] = df2["month"].map(SEASON_MAP)

        overall = df2[val_cols[0]].notna().mean() * 100
        sw = df2[df2["season"] == "southwest-monsoon"][val_cols[0]].notna().mean() * 100
        post = df2[df2["season"] == "post-monsoon"][val_cols[0]].notna().mean() * 100

        rows.append({
            "variable": name,
            "source": "GEE",
            "overall_pct": round(overall, 1),
            "sw_monsoon_pct": round(sw, 1),
            "post_monsoon_pct": round(post, 1),
        })

    table = pd.DataFrame(rows)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    table.to_csv(TABLES_DIR / "missingness_table.csv", index=False)
    return table


def compute_kerala_monsoon_availability(gee_data: dict, stations: pd.DataFrame) -> str:
    """Compute satellite data availability for Kerala Jun-Sep."""
    kerala_ids = stations[stations["state"] == "Kerala"]["station_id"].astype(str).tolist()
    lines = ["## Kerala Monsoon (Jun-Sep) Satellite Availability\n"]

    for name, df in sorted(gee_data.items()):
        if df.empty or name not in ("s5p_no2", "maiac_aod"):
            continue
        kerala_df = df[df["station_id"].isin(kerala_ids)]
        monsoon_df = kerala_df[kerala_df["month"].isin([6, 7, 8, 9])]
        val_cols = [c for c in df.columns
                    if c not in ("station_id", "year", "month",
                                 "buffer_m", "valid_pixel_count")]
        if not val_cols:
            continue
        if monsoon_df.empty:
            lines.append(f"- {name}: no data\n")
            continue
        avail = monsoon_df[val_cols[0]].notna().mean() * 100
        by_month = (
            monsoon_df.groupby("month")[val_cols[0]]
            .apply(lambda x: x.notna().mean() * 100).round(1)
        )
        lines.append(f"- {name}: {avail:.1f}% overall\n")
        for m, v in by_month.items():
            mname = {6:"Jun",7:"Jul",8:"Aug",9:"Sep"}[m]
            lines.append(f"  - {mname}: {v:.1f}%\n")

    return "".join(lines)


def main() -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)

    # Load data
    pm25 = load_pm25_daily()
    stations = pd.read_csv(STATIONS_PATH)
    stations["station_id"] = stations["station_id"].astype(str)
    gee_data = load_all_gee()

    completed = {k: v for k, v in gee_data.items() if not v.empty}
    logger.info(f"GEE datasets loaded: {list(completed.keys())}")

    # Figures
    logger.info("Generating figures ...")
    plot_missingness_by_variable(completed)
    plot_satellite_monthly_availability(completed)
    plot_pm25_seasonality(pm25, stations)
    plot_pm25_distribution(pm25)
    plot_correlation_vs_distance(pm25, stations)

    # Tables
    logger.info("Building tables ...")
    miss_table = build_missingness_table(pm25, completed)
    seasonal_stats = compute_seasonal_stats(pm25)

    # Kerala monsoon text
    kerala_text = compute_kerala_monsoon_availability(completed, stations)

    # Print key numbers
    logger.info("\n" + "="*55)
    logger.info("MISSINGNESS SUMMARY:")
    logger.info(miss_table.to_string(index=False))
    logger.info("\nSEASONAL STATS (all stations):")
    logger.info(seasonal_stats.to_string(index=False))
    logger.info("\n" + kerala_text)
    logger.info("="*55)
    logger.info("Stage 3 EDA complete.")


if __name__ == "__main__":
    main()
