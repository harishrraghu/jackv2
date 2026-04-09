"""Tests for data validator."""

import os
import sys

import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.validator import validate_data


def _make_daily(rows):
    """Create a mock daily DataFrame."""
    data = []
    for r in rows:
        data.append({
            "Instrument": "BANKNIFTY",
            "Date": pd.Timestamp(r["date"]),
            "Time": "9:15:00",
            "Open": r["open"],
            "High": r["high"],
            "Low": r["low"],
            "Close": r["close"],
            "Range": r["high"] - r["low"],
            "Body": abs(r["close"] - r["open"]),
            "Return_pct": (r["close"] - r["open"]) / r["open"] * 100,
            "Bullish": r["close"] > r["open"],
        })
    return pd.DataFrame(data)


def test_valid_data_passes():
    """Test that clean data passes validation."""
    rows = [
        {"date": "2020-01-06", "open": 30000, "high": 30200, "low": 29900, "close": 30100},
        {"date": "2020-01-07", "open": 30100, "high": 30300, "low": 30000, "close": 30200},
        {"date": "2020-01-08", "open": 30200, "high": 30400, "low": 30100, "close": 30350},
    ]
    daily = _make_daily(rows)
    data = {"1d": daily, "2h": pd.DataFrame(), "1h": pd.DataFrame(),
            "15m": pd.DataFrame(), "5m": pd.DataFrame(), "1m": pd.DataFrame()}

    result = validate_data(data)
    assert result["ohlc_violations"] == 0
    assert result["value_outliers"] == 0


def test_ohlc_violation_detected():
    """Test that OHLC violation is detected (High < Close)."""
    rows = [
        {"date": "2020-01-06", "open": 30000, "high": 29800, "low": 29700, "close": 30100},
    ]
    daily = _make_daily(rows)
    data = {"1d": daily, "2h": pd.DataFrame(), "1h": pd.DataFrame(),
            "15m": pd.DataFrame(), "5m": pd.DataFrame(), "1m": pd.DataFrame()}

    result = validate_data(data)
    assert result["ohlc_violations"] > 0
    assert result["passed"] is False


def test_value_outlier_detected():
    """Test that out-of-range values are flagged."""
    rows = [
        {"date": "2020-01-06", "open": 500, "high": 600, "low": 400, "close": 550},
    ]
    daily = _make_daily(rows)
    data = {"1d": daily, "2h": pd.DataFrame(), "1h": pd.DataFrame(),
            "15m": pd.DataFrame(), "5m": pd.DataFrame(), "1m": pd.DataFrame()}

    result = validate_data(data)
    assert result["value_outliers"] > 0
    assert result["passed"] is False
