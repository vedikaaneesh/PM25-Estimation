"""Load YAML configuration files.

Usage:
    from src.utils.config import load_config, CONFIG_DIR

    study = load_config("study_area")
    dates = load_config("dates")
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"


def load_config(name: str) -> dict[str, Any]:
    """Load a YAML config file from configs/ (without .yaml extension).

    Args:
        name: Config filename stem, e.g. "study_area" -> configs/study_area.yaml

    Returns:
        Parsed YAML as a dict.

    Raises:
        FileNotFoundError: If the config file does not exist.
    """
    path = CONFIG_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
