"""Evaluation metrics for PM2.5 estimation models.

All metrics computed on a single function call to avoid inconsistency.
Never fit anything here — pure computation only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def compute_metrics(
    y_true: np.ndarray | pd.Series,
    y_pred: np.ndarray | pd.Series,
    label: str = "",
) -> dict[str, float]:
    """Compute RMSE, MAE, R2, mean bias, and Pearson r.

    Args:
        y_true: Observed PM2.5 values.
        y_pred: Predicted PM2.5 values.
        label: Optional label for the result dict.

    Returns:
        Dict with keys: rmse, mae, r2, bias, pearson_r, n, label.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)

    # Drop NaN pairs
    mask = ~(np.isnan(y_true) | np.isnan(y_pred))
    y_true = y_true[mask]
    y_pred = y_pred[mask]
    n = len(y_true)

    if n < 3:
        return {"rmse": np.nan, "mae": np.nan, "r2": np.nan,
                "bias": np.nan, "pearson_r": np.nan, "n": n, "label": label}

    residuals = y_pred - y_true
    rmse = float(np.sqrt(np.mean(residuals ** 2)))
    mae = float(np.mean(np.abs(residuals)))
    ss_res = np.sum(residuals ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else np.nan
    bias = float(np.mean(residuals))
    pearson_r, _ = stats.pearsonr(y_true, y_pred)

    return {
        "rmse": round(rmse, 3),
        "mae": round(mae, 3),
        "r2": round(r2, 4),
        "bias": round(bias, 3),
        "pearson_r": round(float(pearson_r), 4),
        "n": n,
        "label": label,
    }


def metrics_by_group(
    df: pd.DataFrame,
    y_true_col: str,
    y_pred_col: str,
    group_col: str,
) -> pd.DataFrame:
    """Compute metrics for each group (season, cloud bin, station, etc.).

    Args:
        df: DataFrame with y_true, y_pred, and group columns.
        y_true_col: Column name for observed values.
        y_pred_col: Column name for predicted values.
        group_col: Column to group by.

    Returns:
        DataFrame with one row per group.
    """
    rows = []
    for group, gdf in df.groupby(group_col):
        m = compute_metrics(gdf[y_true_col], gdf[y_pred_col], label=str(group))
        m[group_col] = group
        rows.append(m)

    # Overall
    overall = compute_metrics(df[y_true_col], df[y_pred_col], label="overall")
    overall[group_col] = "overall"
    rows.append(overall)

    return pd.DataFrame(rows).sort_values(group_col)
