"""Load and combine GEE extraction CSVs into a single DataFrame per dataset."""
from __future__ import annotations

from pathlib import Path
import pandas as pd

GEE_DIR = Path("data/raw/gee_extracts")


def load_gee_dataset(dataset: str) -> pd.DataFrame:
    """Load all monthly CSVs for a GEE dataset into one DataFrame.

    Args:
        dataset: Dataset name (e.g. 's5p_no2').

    Returns:
        DataFrame with all months combined, or empty DataFrame if no files.
    """
    p = GEE_DIR / dataset
    files = sorted(p.glob("*.csv")) if p.exists() else []
    if not files:
        return pd.DataFrame()
    dfs = [pd.read_csv(f) for f in files]
    return pd.concat(dfs, ignore_index=True)


def load_all_gee() -> dict[str, pd.DataFrame]:
    """Load all available GEE datasets.

    Returns:
        Dict mapping dataset name to DataFrame.
    """
    datasets = [d.name for d in GEE_DIR.iterdir() if d.is_dir()]
    return {d: load_gee_dataset(d) for d in sorted(datasets)}
