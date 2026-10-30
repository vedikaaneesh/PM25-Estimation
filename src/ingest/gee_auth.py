"""Google Earth Engine authentication using service account.

Reads the GEE config from configs/gee.yaml and authenticates using
the service account key file. The key file must be placed at the
path specified in configs/gee.yaml (default:
~/.config/earthengine/pm25-service-account-key.json).

Usage:
    from src.ingest.gee_auth import initialize_ee
    initialize_ee()
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import ee

from src.utils.config import load_config
from src.utils.env import load_env
from src.utils.logging_config import setup_logging

load_env()
logger = setup_logging()


def initialize_ee() -> ee:
    """Initialize Earth Engine with service account authentication.

    Returns:
        The ee module (initialized).

    Raises:
        FileNotFoundError: If the service account key file is not found.
        RuntimeError: If authentication fails.
    """
    config = load_config("gee")
    project_id = config["project_id"]
    service_account = config["service_account"]
    key_path = Path(
        os.path.expanduser(config.get("private_key_path", ""))
    )

    if not key_path.exists():
        logger.error(
            f"Service account key not found at {key_path}\n"
            f"Place the JSON key file there before running GEE extraction."
        )
        raise FileNotFoundError(f"Key file not found: {key_path}")

    try:
        credentials = ee.ServiceAccountCredentials(
            service_account, str(key_path)
        )
        ee.Initialize(
            credentials,
            project=project_id,
            opt_url="https://earthengine-highvolume.googleapis.com",
        )
        logger.info(
            f"Earth Engine initialized: project={project_id}, "
            f"account={service_account}"
        )
        return ee
    except Exception as e:
        logger.error(f"Earth Engine authentication failed: {e}")
        raise RuntimeError(f"GEE auth failed: {e}") from e
