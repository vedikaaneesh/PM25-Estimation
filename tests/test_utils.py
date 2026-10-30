"""Tests for config loading, experiment log, and station utilities."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from src.utils.config import load_config
from src.utils.experiment_log import init_log, log_run
from src.ingest.completeness_audit import get_season


class TestConfig:
    """Config loading tests."""

    def test_load_study_area(self):
        cfg = load_config("study_area")
        assert "states" in cfg
        assert "bbox" in cfg
        assert "Kerala" in cfg["states"]

    def test_load_dates(self):
        cfg = load_config("dates")
        assert "study_period" in cfg
        assert "seasons" in cfg

    def test_load_thresholds(self):
        cfg = load_config("thresholds")
        assert "station_completeness" in cfg
        assert cfg["station_completeness"]["min_daily_pct"] == 70

    def test_missing_config_raises(self):
        with pytest.raises(FileNotFoundError):
            load_config("nonexistent_config")


class TestExperimentLog:
    """Experiment log tests."""

    def test_log_run(self, tmp_path, monkeypatch):
        import src.utils.experiment_log as elog

        log_path = tmp_path / "experiment_log.csv"
        monkeypatch.setattr(elog, "LOG_PATH", log_path)

        run_id = log_run({"model": "random_forest", "rmse": 12.5})
        assert run_id != ""

        df = pd.read_csv(log_path)
        assert len(df) == 1
        assert df.iloc[0]["model"] == "random_forest"
        assert df.iloc[0]["rmse"] == 12.5


class TestSeasonMapping:
    """Season mapping tests."""

    @pytest.mark.parametrize("month,expected", [
        (1, "post-monsoon"),
        (2, "post-monsoon"),
        (3, "pre-monsoon"),
        (5, "pre-monsoon"),
        (6, "southwest-monsoon"),
        (9, "southwest-monsoon"),
        (10, "northeast-monsoon"),
        (12, "northeast-monsoon"),
    ])
    def test_get_season(self, month, expected):
        assert get_season(month) == expected


class TestStateAssignment:
    """State assignment by coordinates tests."""

    def test_kerala_point(self):
        from src.ingest.merge_stations import assign_state_by_coords
        assert assign_state_by_coords(10.0, 76.5) == "Kerala"

    def test_unknown_point(self):
        from src.ingest.merge_stations import assign_state_by_coords
        assert assign_state_by_coords(40.0, -74.0) == "Unknown"

    def test_none_coords(self):
        from src.ingest.merge_stations import assign_state_by_coords
        assert assign_state_by_coords(None, None) == "Unknown"
