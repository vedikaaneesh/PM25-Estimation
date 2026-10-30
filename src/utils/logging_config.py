"""Logging configuration for the PM2.5 pipeline.

All modules should call setup_logging() once at start, then use
logging.getLogger("pm25") throughout.
"""
import logging
import sys
from pathlib import Path

LOG_DIR = Path("reports/logs")


def setup_logging(name: str = "pm25", level: int = logging.INFO) -> logging.Logger:
    """Configure and return a logger with console + file handlers.

    Args:
        name: Logger name (used for log filename).
        level: Logging level.

    Returns:
        Configured Logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # File
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_h = logging.FileHandler(LOG_DIR / f"{name}.log")
    file_h.setLevel(level)
    file_h.setFormatter(fmt)
    logger.addHandler(file_h)

    return logger
