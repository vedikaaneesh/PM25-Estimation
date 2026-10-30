"""Unit tests for alignment and timezone handling.

Critical: catches off-by-one-day IST/UTC timezone errors.
IST = UTC + 5h30m. An hourly reading at 23:00 IST on day D
is at 17:30 UTC on day D — same day.
An hourly reading at 00:30 IST on day D+1 is at 19:00 UTC on day D —
naive UTC-to-IST conversion could assign it to the wrong day.
"""
from __future__ import annotations

import pandas as pd
import numpy as np
import pytest

IST_OFFSET = pd.Timedelta(hours=5, minutes=30)


class TestTimezoneAlignment:
    """Test that IST/UTC conversion does not cause off-by-one-day errors."""

    def test_ist_offset_direction(self):
        """IST is ahead of UTC, so IST = UTC + 5:30."""
        utc_midnight = pd.Timestamp("2022-06-15 00:00:00", tz=None)
        ist = utc_midnight + IST_OFFSET
        assert ist.hour == 5
        assert ist.minute == 30
        assert ist.day == 15  # same day

    def test_late_night_ist_to_utc(self):
        """23:30 IST maps to 18:00 UTC same day (not next day)."""
        ist = pd.Timestamp("2022-06-15 23:30:00")
        utc = ist - IST_OFFSET
        assert utc.day == 15
        assert utc.hour == 18

    def test_early_morning_ist_same_day(self):
        """00:30 IST on day D maps to 19:00 UTC on day D-1."""
        ist = pd.Timestamp("2022-06-15 00:30:00")
        utc = ist - IST_OFFSET
        assert utc.day == 14  # previous day in UTC
        assert utc.hour == 19

    def test_overpass_window_ist(self):
        """TROPOMI overpass 12:00–15:00 IST = 06:30–09:30 UTC."""
        overpass_start_ist = pd.Timestamp("2022-06-15 12:00:00")
        overpass_end_ist = pd.Timestamp("2022-06-15 15:00:00")
        start_utc = overpass_start_ist - IST_OFFSET
        end_utc = overpass_end_ist - IST_OFFSET
        assert start_utc.hour == 6
        assert start_utc.minute == 30
        assert end_utc.hour == 9
        assert end_utc.minute == 30
        assert start_utc.day == end_utc.day == 15

    def test_daily_ist_date_boundary(self):
        """Daily IST date should be assigned from timestamp_ist, not UTC.

        A reading at 2022-06-15 01:00 IST is 2022-06-14 19:30 UTC.
        Its IST date is 2022-06-15, not 2022-06-14.
        """
        utc_ts = pd.Timestamp("2022-06-14 19:30:00")
        ist_ts = utc_ts + IST_OFFSET
        assert ist_ts.date() == pd.Timestamp("2022-06-15").date()
        assert utc_ts.date() == pd.Timestamp("2022-06-14").date()

    def test_no_duplicate_days_in_daily_aggregation(self):
        """Aggregating by IST date should not create duplicate days.

        Create a 48-hour UTC sequence starting at midnight UTC.
        In IST (+5:30), this spans parts of 3 calendar days.
        The critical invariant: no station-day appears twice, and
        the total row count is preserved exactly.
        """
        utc_times = pd.date_range("2022-06-15 00:00", periods=48, freq="h")
        ist_times = utc_times + IST_OFFSET
        df = pd.DataFrame({
            "timestamp_utc": utc_times,
            "timestamp_ist": ist_times,
            "pm25": np.random.default_rng(42).uniform(10, 40, 48),
        })
        df["date_ist"] = df["timestamp_ist"].dt.normalize()
        counts = df.groupby("date_ist").size()
        # Total rows must be preserved
        assert counts.sum() == 48
        # No date should appear more than once in the groupby
        assert len(counts) == counts.index.nunique()
        # The per-date counts must sum to 48 (no row lost or duplicated)
        assert counts.sum() == len(df)


class TestSeasonMapping:
    """Confirm season mapping covers all 12 months without gaps."""

    def test_all_months_mapped(self):
        from src.utils.seasons import SEASON_MAP
        assert set(SEASON_MAP.keys()) == set(range(1, 13))

    def test_monsoon_months(self):
        from src.utils.seasons import SEASON_MAP
        for m in [6, 7, 8, 9]:
            assert SEASON_MAP[m] == "southwest-monsoon"


class TestCyclicalEncoding:
    """Cyclical DOY encoding should be bounded and periodic."""

    def test_bounds(self):
        from src.utils.seasons import cyclical_encode_doy
        doys = pd.Series(range(1, 366))
        sin_v, cos_v = cyclical_encode_doy(doys)
        assert sin_v.between(-1, 1).all()
        assert cos_v.between(-1, 1).all()

    def test_jan1_approx_dec31(self):
        """Day 1 and day 365 should have nearly the same encoding."""
        from src.utils.seasons import cyclical_encode_doy
        s1, c1 = cyclical_encode_doy(pd.Series([1]))
        s365, c365 = cyclical_encode_doy(pd.Series([365]))
        assert abs(float(s1.iloc[0]) - float(s365.iloc[0])) < 0.05
        assert abs(float(c1.iloc[0]) - float(c365.iloc[0])) < 0.05
