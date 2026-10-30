"""Stage 5: Run all baseline models and produce evaluation results.

Evaluates each model under three split strategies:
  - temporal   : train 2021-2023, test 2024
  - loso        : leave-one-station-out
  - combined    : held-out stations + held-out year

Reports metrics: overall, per season, per cloud-fraction bin.
Produces scatter plots, residual plots, per-station spread, and
a feature importance plot for Random Forest.

Usage:
    python -m src.eval.run_baselines
"""
from __future__ import annotations

import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.eval.metrics import compute_metrics, metrics_by_group
from src.eval.splits import temporal_split, loso_splits, combined_split
from src.models.baselines import (
    ClimatologyModel, fit_linear, fit_rf, predict,
    predict_persistence, get_feature_cols,
)
from src.utils.config import load_config
from src.utils.env import load_env
from src.utils.experiment_log import log_run
from src.utils.logging_config import setup_logging

load_env()
logger = setup_logging()

TIER_A_PATH = Path("data/processed/features_tier_a.csv")
TIER_B_PATH = Path("data/processed/features_tier_b.csv")
FIGURES_DIR = Path("reports/figures")
TABLES_DIR = Path("reports/tables")
RESULTS_PATH = Path("reports/tables/baseline_results.csv")
RANDOM_SEED = 42

# WHO and India NAAQS reference lines
WHO_24H = 15.0
NAAQS_24H = 60.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_features() -> tuple[pd.DataFrame, pd.DataFrame]:
    tier_a = pd.read_csv(TIER_A_PATH)
    tier_b = pd.read_csv(TIER_B_PATH)
    logger.info(f"Tier A: {len(tier_a):,} rows, {tier_a.shape[1]} cols")
    logger.info(f"Tier B: {len(tier_b):,} rows, {tier_b.shape[1]} cols")
    return tier_a, tier_b


def results_row(
    model: str, tier: str, split: str,
    y_true: np.ndarray, y_pred: np.ndarray
) -> dict:
    m = compute_metrics(y_true, y_pred)
    m.update({"model": model, "tier": tier, "split": split})
    return m


# ── Plotting ──────────────────────────────────────────────────────────────────

def plot_scatter(
    y_true: np.ndarray, y_pred: np.ndarray,
    title: str, out_path: Path,
) -> None:
    """Predicted vs observed scatter plot with WHO/NAAQS lines."""
    fig, ax = plt.subplots(figsize=(6, 6))
    lim = max(y_true.max(), y_pred.max()) * 1.05
    ax.scatter(y_true, y_pred, alpha=0.3, s=10, color="#1f77b4")
    ax.plot([0, lim], [0, lim], "k--", linewidth=1, label="1:1")
    ax.axvline(WHO_24H, color="green", linestyle=":", linewidth=1,
               label=f"WHO 24h ({WHO_24H})")
    ax.axvline(NAAQS_24H, color="red", linestyle=":", linewidth=1,
               label=f"NAAQS ({NAAQS_24H})")
    m = compute_metrics(y_true, y_pred)
    ax.set_xlabel("Observed PM2.5 (µg/m³)")
    ax.set_ylabel("Predicted PM2.5 (µg/m³)")
    ax.set_title(f"{title}\nRMSE={m['rmse']:.2f}  R²={m['r2']:.3f}  n={m['n']}")
    ax.legend(fontsize=8)
    plt.tight_layout()
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_residuals_by_season(
    test_df: pd.DataFrame,
    y_pred: np.ndarray,
    title: str,
    out_path: Path,
) -> None:
    """Box plot of residuals by season."""
    df = test_df.copy()
    df["residual"] = y_pred - df["pm25_daily_mean"].values

    SEASON_ORDER = [
        "post-monsoon", "pre-monsoon",
        "southwest-monsoon", "northeast-monsoon",
    ]
    COLORS = {
        "post-monsoon": "#1f77b4", "pre-monsoon": "#ff7f0e",
        "southwest-monsoon": "#2ca02c", "northeast-monsoon": "#d62728",
    }
    data = [df[df["season"] == s]["residual"].dropna().values
            for s in SEASON_ORDER]

    fig, ax = plt.subplots(figsize=(8, 4))
    bp = ax.boxplot(
        data,
        tick_labels=[s.replace("-", "\n") for s in SEASON_ORDER],
        patch_artist=True,
        medianprops={"color": "black", "linewidth": 2},
        flierprops={"marker": ".", "markersize": 2, "alpha": 0.3},
    )
    for patch, s in zip(bp["boxes"], SEASON_ORDER):
        patch.set_facecolor(COLORS[s])
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylabel("Residual (pred − obs) µg/m³")
    ax.set_title(f"Residuals by Season — {title}")
    plt.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_per_station_spread(
    test_df: pd.DataFrame,
    y_pred: np.ndarray,
    title: str,
    out_path: Path,
    stations_path: Path = Path("data/interim/stations_merged.csv"),
) -> None:
    """RMSE per station sorted by value."""
    df = test_df.copy()
    df["y_pred"] = y_pred
    rows = []
    for sid, gdf in df.groupby("station_id"):
        m = compute_metrics(gdf["pm25_daily_mean"], gdf["y_pred"])
        state = gdf["state"].iloc[0] if "state" in gdf.columns else ""
        rows.append({"station_id": sid, "rmse": m["rmse"],
                     "r2": m["r2"], "n": m["n"], "state": state})
    sdf = pd.DataFrame(rows).dropna(subset=["rmse"]).sort_values("rmse")

    STATE_COLORS = {
        "Kerala": "#2ca02c", "Karnataka": "#1f77b4",
        "Tamil Nadu": "#ff7f0e", "Andhra Pradesh": "#d62728",
        "Telangana": "#9467bd",
    }
    colors = [STATE_COLORS.get(s, "#7f7f7f") for s in sdf["state"]]

    fig, ax = plt.subplots(figsize=(max(10, len(sdf) * 0.25), 5))
    ax.bar(range(len(sdf)), sdf["rmse"], color=colors)
    ax.set_xticks([])
    ax.set_xlabel("Station (sorted by RMSE)")
    ax.set_ylabel("RMSE (µg/m³)")
    ax.set_title(f"Per-Station RMSE — {title}")
    # Legend for states
    handles = [plt.Rectangle((0, 0), 1, 1, color=c)
               for c in STATE_COLORS.values()]
    ax.legend(handles, STATE_COLORS.keys(), fontsize=8, loc="upper left")
    plt.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_feature_importance(
    pipe, feature_cols: list[str], title: str, out_path: Path,
    top_n: int = 20,
) -> None:
    """Horizontal bar chart of RF feature importances (top N)."""
    rf = pipe.named_steps["model"]
    imps = pd.Series(rf.feature_importances_, index=feature_cols)
    top = imps.sort_values(ascending=False).head(top_n)

    fig, ax = plt.subplots(figsize=(8, 6))
    top.sort_values().plot.barh(ax=ax, color="#1f77b4")
    ax.set_xlabel("Feature importance (mean decrease impurity)")
    ax.set_title(f"RF Feature Importance — {title}")
    plt.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# ── Ablation ──────────────────────────────────────────────────────────────────

def run_ablation(
    train: pd.DataFrame,
    test: pd.DataFrame,
    all_feature_cols: list[str],
) -> pd.DataFrame:
    """RF ablation: met-only → +S5P gases → +AER_AI → all Tier A features."""
    met_cols = [c for c in all_feature_cols
                if any(k in c for k in
                       ["era5", "wind_speed", "relative_humidity",
                        "lag", "doy", "precipitation"])]
    s5p_gas_cols = [c for c in all_feature_cols
                    if any(k in c for k in
                           ["no2", "co", "so2", "hcho"])]
    aerosol_cols = [c for c in all_feature_cols
                    if any(k in c for k in ["aer_ai", "aod", "maiac"])]

    sets = {
        "met_only": met_cols,
        "met+s5p_gases": met_cols + s5p_gas_cols,
        "met+s5p+aerosol": met_cols + s5p_gas_cols + aerosol_cols,
        "all_tier_a": all_feature_cols,
    }

    rows = []
    for label, cols in sets.items():
        cols_available = [c for c in cols if c in train.columns]
        if not cols_available:
            continue
        # Build a fresh train/test slice with only these columns
        train_sub = train[cols_available + ["pm25_daily_mean"]].copy()
        test_sub = test[cols_available + ["pm25_daily_mean"]].copy()
        pipe = fit_rf(train_sub, cols_available, n_estimators=200)
        y_pred = predict(pipe, test_sub, cols_available)
        y_true = test_sub["pm25_daily_mean"].values
        m = compute_metrics(y_true, y_pred, label=label)
        m["feature_set"] = label
        m["n_features"] = len(cols_available)
        rows.append(m)
        logger.info(f"  Ablation {label:20s}: RMSE={m['rmse']:.2f}, "
                    f"R²={m['r2']:.3f}, n_feat={len(cols_available)}")

    return pd.DataFrame(rows)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)

    tier_a, tier_b = load_features()
    all_results = []

    # ── 1. Temporal split ─────────────────────────────────────────────────────
    logger.info("\n=== TEMPORAL SPLIT (train 2021-2023, test 2024) ===")

    for tier_name, df in [("tier_a", tier_a), ("tier_b", tier_b)]:
        train, test = temporal_split(df)
        feat_cols = get_feature_cols(df)
        y_true = test["pm25_daily_mean"].values

        # Persistence
        y_pers = predict_persistence(train, test)
        all_results.append(results_row("persistence", tier_name,
                                       "temporal", y_true, y_pers))

        # Climatology
        clim = ClimatologyModel().fit(train)
        y_clim = clim.predict(test)
        all_results.append(results_row("climatology", tier_name,
                                       "temporal", y_true, y_clim))

        # Linear
        pipe_lr = fit_linear(train, feat_cols)
        y_lr = predict(pipe_lr, test, feat_cols)
        all_results.append(results_row("linear_regression", tier_name,
                                       "temporal", y_true, y_lr))

        # Random Forest
        pipe_rf = fit_rf(train, feat_cols)
        y_rf = predict(pipe_rf, test, feat_cols)
        all_results.append(results_row("random_forest", tier_name,
                                       "temporal", y_true, y_rf))
        log_run({
            "stage": "5_baselines", "model": "random_forest",
            "tier": tier_name, "split_type": "temporal",
            "rmse": all_results[-1]["rmse"], "r2": all_results[-1]["r2"],
        })

        if tier_name == "tier_a":
            plot_scatter(y_true, y_rf,
                         "Random Forest Tier A — Temporal Split",
                         FIGURES_DIR / "rf_tier_a_temporal_scatter.png")
            plot_residuals_by_season(test, y_rf,
                         "Random Forest Tier A",
                         FIGURES_DIR / "rf_tier_a_residuals_by_season.png")
            plot_per_station_spread(test, y_rf,
                         "Random Forest Tier A — Temporal",
                         FIGURES_DIR / "rf_tier_a_per_station_rmse.png")
            plot_feature_importance(pipe_rf, feat_cols,
                         "Tier A — Temporal",
                         FIGURES_DIR / "rf_tier_a_feature_importance.png")

    # ── 2. Spatial: Blocked 5-fold ────────────────────────────────────────────
    logger.info("\n=== SPATIAL BLOCKED 5-FOLD ===")

    for tier_name, df in [("tier_a", tier_a), ("tier_b", tier_b)]:
        feat_cols = get_feature_cols(df)
        fold_results = []
        from src.eval.splits import spatial_block_kfold
        for train_f, test_f, fold in spatial_block_kfold(df, n_splits=5):
            pipe = fit_rf(train_f, feat_cols)
            y_pred = predict(pipe, test_f, feat_cols)
            y_true = test_f["pm25_daily_mean"].values
            m = compute_metrics(y_true, y_pred)
            fold_results.append(m)

        # Average across folds
        avg = {k: round(np.mean([r[k] for r in fold_results
                                  if isinstance(r[k], float)]), 3)
               for k in ["rmse", "mae", "r2", "bias", "pearson_r"]}
        avg.update({"model": "random_forest", "tier": tier_name,
                    "split": "spatial_blocked_kfold", "n": sum(r["n"] for r in fold_results),
                    "label": ""})
        all_results.append(avg)

    # ── 3. LOSO (leave-one-station-out) ───────────────────────────────────────
    logger.info("\n=== LEAVE-ONE-STATION-OUT (RF, Tier A) ===")

    loso_rows = []
    from src.eval.splits import loso_splits
    feat_cols_a = get_feature_cols(tier_a)

    for train_l, test_l, sid in loso_splits(tier_a):
        if len(test_l) < 3:
            continue
        pipe = fit_rf(train_l, feat_cols_a, n_estimators=100)
        y_pred = predict(pipe, test_l, feat_cols_a)
        y_true = test_l["pm25_daily_mean"].values
        m = compute_metrics(y_true, y_pred, label=sid)
        m["station_id"] = sid
        loso_rows.append(m)

    loso_df = pd.DataFrame(loso_rows)
    loso_df.to_csv(TABLES_DIR / "loso_results.csv", index=False)
    logger.info(f"LOSO: mean RMSE={loso_df['rmse'].mean():.2f}, "
                f"mean R²={loso_df['r2'].mean():.3f}")

    # Overall LOSO as a row in main results
    all_results.append({
        "model": "random_forest", "tier": "tier_a",
        "split": "loso",
        "rmse": round(loso_df["rmse"].mean(), 3),
        "mae": round(loso_df["mae"].mean(), 3),
        "r2": round(loso_df["r2"].mean(), 3),
        "bias": round(loso_df["bias"].mean(), 3),
        "pearson_r": round(loso_df["pearson_r"].mean(), 3),
        "n": loso_df["n"].sum(), "label": "",
    })

    # ── 4. Season-stratified metrics (temporal split, RF Tier A) ─────────────
    logger.info("\n=== SEASON-STRATIFIED METRICS (RF Tier A, temporal) ===")

    train_a, test_a = temporal_split(tier_a)
    feat_cols_a = get_feature_cols(tier_a)
    pipe_rf_a = fit_rf(train_a, feat_cols_a)
    test_a = test_a.copy()
    test_a["y_pred"] = predict(pipe_rf_a, test_a, feat_cols_a)

    season_metrics = metrics_by_group(
        test_a, "pm25_daily_mean", "y_pred", "season"
    )
    season_metrics.to_csv(TABLES_DIR / "rf_tier_a_season_metrics.csv", index=False)
    logger.info("\n" + season_metrics[["season", "rmse", "r2", "n"]].to_string(index=False))

    # Cloud-fraction bin metrics
    if "cloud_fraction_bin" in test_a.columns:
        cloud_metrics = metrics_by_group(
            test_a.dropna(subset=["cloud_fraction_bin"]),
            "pm25_daily_mean", "y_pred", "cloud_fraction_bin"
        )
        cloud_metrics.to_csv(TABLES_DIR / "rf_tier_a_cloud_metrics.csv", index=False)

    # ── 5. Ablation ───────────────────────────────────────────────────────────
    logger.info("\n=== FEATURE ABLATION (RF, temporal split) ===")

    ablation_df = run_ablation(train_a, test_a, feat_cols_a)
    ablation_df.to_csv(TABLES_DIR / "ablation_results.csv", index=False)

    # Plot ablation RMSE
    fig, ax = plt.subplots(figsize=(8, 4))
    abl = ablation_df.sort_values("rmse")
    ax.barh(abl["feature_set"], abl["rmse"], color="#1f77b4")
    ax.set_xlabel("RMSE (µg/m³)")
    ax.set_title("Feature Ablation — Random Forest (Temporal Split)")
    for i, (_, row) in enumerate(abl.iterrows()):
        ax.text(row["rmse"] + 0.1, i,
                f"R²={row['r2']:.3f}, n={int(row['n_features'])} feat",
                va="center", fontsize=9)
    plt.tight_layout()
    fig.savefig(FIGURES_DIR / "ablation_rmse.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # ── 6. Save all results ───────────────────────────────────────────────────
    results_df = pd.DataFrame(all_results)
    results_df.to_csv(RESULTS_PATH, index=False)
    logger.info(f"\nAll results saved to {RESULTS_PATH}")

    # Print summary table
    summary = results_df[results_df["split"] == "temporal"][
        ["model", "tier", "rmse", "mae", "r2", "bias", "pearson_r", "n"]
    ].sort_values(["tier", "rmse"])
    logger.info("\n=== TEMPORAL SPLIT SUMMARY ===")
    logger.info("\n" + summary.to_string(index=False))


if __name__ == "__main__":
    main()
