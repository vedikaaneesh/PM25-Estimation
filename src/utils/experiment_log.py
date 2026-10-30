"""CSV-based experiment tracking.

Simple, version-controllable alternative to MLflow. Each run is one row
in reports/experiment_log.csv. Init once, then call log_run() for each
experiment.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

LOG_PATH = Path("reports/experiment_log.csv")

FIELDNAMES = [
    "run_id",
    "timestamp",
    "stage",
    "model",
    "tier",
    "feature_set",
    "split_type",
    "rmse",
    "mae",
    "r2",
    "bias",
    "pearson_r",
    "notes",
]


def init_log() -> None:
    """Create the experiment log CSV with headers if it doesn't exist."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_PATH.exists():
        with open(LOG_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()


def log_run(run_data: dict[str, Any]) -> str:
    """Append a run to the experiment log.

    Args:
        run_data: Dict with any of FIELDNAMES keys. Missing keys default
            to empty string except run_id and timestamp which are auto-filled.

    Returns:
        The run_id string.
    """
    init_log()
    run_id = run_data.setdefault(
        "run_id", datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    run_data.setdefault("timestamp", datetime.now().isoformat())

    row = {k: run_data.get(k, "") for k in FIELDNAMES}
    with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writerow(row)

    return run_id
