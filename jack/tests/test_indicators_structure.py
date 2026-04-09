"""Tests for structure indicators (pivots, streaks, gap, ORB)."""

import os
import sys

import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indicators.pivots import compute as pivots_compute
from indicators.streaks import compute as streaks_compute
from indicators.gap import compute as gap_compute
from indicators.orb import compute_single_day as orb_single_day


class TestPivots:
    def test_uses_previous_row(self):
        """Test that pivots use PREVIOUS row's HLC, not current."""
        data = {
            "Date": pd.date_range("2020-01-06", periods=3),
            "Open": [30000, 30100, 30200],
            "High": [30200, 30300, 30400],
            "Low": [29800, 29900, 30000],
            "Close": [30100, 30200, 30300],
            "Time": ["9:15:00"] * 3,
        }
        df = pd.DataFrame(data)
        result = pivots_compute(df)

        # First row should have NaN (no previous data)
        assert pd.isna(result.iloc[0]["PP"])

        # Second row's PP should use first row's HLC
        expected_pp = (30200 + 29800 + 30100) / 3  # First row's H, L, C
        assert abs(result.iloc[1]["PP"] - expected_pp) < 0.01


class TestStreaks:
    def test_streak_counter(self):
        """Test streak counter resets correctly."""
        data = {
            "Date": pd.date_range("2020-01-06", periods=5),
            "Open": [100, 100, 100, 100, 100],
            "High": [120, 120, 120, 120, 120],
            "Low": [80, 80, 80, 80, 80],
            "Close": [110, 115, 120, 90, 95],  # Bull, Bull, Bull, Bear, Bear
            "Time": ["9:15:00"] * 5,
        }
        df = pd.DataFrame(data)
        result = streaks_compute(df)

        assert list(result["Bull_Streak"]) == [1, 2, 3, 0, 0]
        assert list(result["Bear_Streak"]) == [0, 0, 0, 1, 2]


class TestGap:
    def test_gap_classification(self):
        """Test gap classification boundaries."""
        data = {
            "Date": pd.date_range("2020-01-06", periods=4),
            "Open": [30000, 30200, 29800, 30100],
            "High": [30100, 30300, 29900, 30200],
            "Low": [29900, 30100, 29700, 30000],
            "Close": [30050, 30250, 29850, 30150],
            "Time": ["9:15:00"] * 4,
        }
        df = pd.DataFrame(data)
        result = gap_compute(df)

        # Second row gap: 30200 - 30050 = 150 pts, 150/30050 = 0.50%
        assert result.iloc[1]["Gap_Type"] in ("small_up", "large_up")

    def test_gap_direction(self):
        """Test gap points sign."""
        data = {
            "Date": pd.date_range("2020-01-06", periods=2),
            "Open": [30000, 29800],
            "High": [30100, 29900],
            "Low": [29900, 29700],
            "Close": [30050, 29850],
            "Time": ["9:15:00"] * 2,
        }
        df = pd.DataFrame(data)
        result = gap_compute(df)

        # Gap down: 29800 - 30050 < 0
        assert result.iloc[1]["Gap_Pts"] < 0


class TestORB:
    def test_orb_extraction(self):
        """Test ORB extraction from mock 15m data."""
        data = {
            "Date": [pd.Timestamp("2020-01-06")] * 3,
            "Open": [30000, 30050, 30100],
            "High": [30100, 30120, 30150],
            "Low": [29950, 30000, 30050],
            "Close": [30050, 30100, 30120],
            "Time": ["9:15:00", "9:30:00", "9:45:00"],
        }
        df = pd.DataFrame(data)
        orb = orb_single_day(df)

        assert orb["ORB_High"] == 30100  # First candle's high
        assert orb["ORB_Low"] == 29950   # First candle's low
        assert orb["ORB_Range"] == 150
        assert orb["ORB_Bullish"] is True  # Close > Open

    def test_orb_empty(self):
        """Test ORB with empty data."""
        orb = orb_single_day(pd.DataFrame())
        assert np.isnan(orb["ORB_High"])
