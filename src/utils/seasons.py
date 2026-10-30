"""Season and temporal utility functions shared across stages."""
from __future__ import annotations

import numpy as np
import pandas as pd


SEASON_MAP = {
    1: "post-monsoon", 2: "post-monsoon",
    3: "pre-monsoon",  4: "pre-monsoon",  5: "pre-monsoon",
    6: "southwest-monsoon", 7: "southwest-monsoon",
    8: "southwest-monsoon", 9: "southwest-monsoon",
    10: "northeast-monsoon", 11: "northeast-monsoon",
    12: "northeast-monsoon",
}

SEASON_ORDER = [
    "post-monsoon", "pre-monsoon",
    "southwest-monsoon", "northeast-monsoon",
]


def add_temporal_columns(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    """Add year, month, season, doy columns from a date column.

    Args:
        df: DataFrame with a datetime column.
        date_col: Name of the datetime column.

    Returns:
        DataFrame with added columns: year, month, season, day_of_year.
    """
    df = df.copy()
    dt = pd.to_datetime(df[date_col], errors="coerce")
    df["year"] = dt.dt.year
    df["month"] = dt.dt.month
    df["day_of_year"] = dt.dt.dayofyear
    df["season"] = df["month"].map(SEASON_MAP)
    return df


def cyclical_encode_doy(doy: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Encode day-of-year as sine/cosine pair (cyclical encoding).

    Args:
        doy: Day-of-year (1–365 or 1–366).

    Returns:
        Tuple of (sin_doy, cos_doy) Series.
    """
    angle = 2 * np.pi * doy / 365.25
    return np.sin(angle), np.cos(angle)
