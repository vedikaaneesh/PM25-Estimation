"""Load .env file into os.environ without external dependencies.

Usage (call once at script start):
    from src.utils.env import load_env
    load_env()
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def load_env() -> None:
    """Read .env file and set key=value pairs into os.environ.

    Skips blank lines and comments (lines starting with #).
    Does not overwrite existing environment variables.
    """
    if not ENV_FILE.exists():
        return

    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key and value:
                # Always prefer .env file values (user explicitly set them)
                os.environ[key] = value
