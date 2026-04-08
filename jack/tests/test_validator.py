"""Tests for jack/data/validator.py"""

import pandas as pd
import pytest

from data.validator import validate_data

INTRADAY_TFS = ["2h", "1h", "15m", "5m", "1m"]


def _make_row(date, open_, high, low, close, time="09:15"):
    return {
        "Date": pd.Timestamp(date),
        "Time": time,
        "Open": float(open_),
        "High": float(high),
        "Low": float(low),
        "Close": float(close),
        "Range": float(high - low),
        "Body": abs(float(close - open_)),
        "Return_pct": (float(close) - float(open_)) / float(open_) * 100,
        "Bullish": close > open_,
    }


def _make_df(rows):
    return pd.DataFrame(rows)


def _empty_intraday():
    return {tf: pd.DataFrame() for tf in INTRADAY_TFS}


def _clean_data():
    """Build a minimal clean dataset that should pass."""
    daily_rows = [
        _make_row("2022-01-03", 38000, 38500, 37800, 38200),
        _make_row("2022-01-04", 38200, 38600, 38000, 38400),
    ]
    data = {"1d": _make_df(daily_rows)}
    data.update(_empty_intraday())
    return data


# ---------------------------------------------------------------------------
# OHLC violation: High < Open
# ---------------------------------------------------------------------------

def test_ohlc_violation_detected():
    rows = [_make_row("2022-01-03", 38500, 38000, 37800, 38200)]  # High < Open
    data = {"1d": _make_df(rows)}
    data.update(_empty_intraday())
    result = validate_data(data)
    assert result["ohlc_violations"] > 0
    assert result["passed"] is False


# ---------------------------------------------------------------------------
# Date gap: 4+ missing calendar days
# ---------------------------------------------------------------------------

def test_date_gap_detected():
    # Jan 3 -> Jan 10: gap of 7 days
    rows = [
        _make_row("2022-01-03", 38000, 38500, 37800, 38200),
        _make_row("2022-01-10", 38200, 38700, 38000, 38500),
    ]
    data = {"1d": _make_df(rows)}
    data.update(_empty_intraday())
    result = validate_data(data)
    assert len(result["date_gaps"]) == 1
    gap = result["date_gaps"][0]
    assert gap[2] == 7


# ---------------------------------------------------------------------------
# Value outlier: Close < 1000
# ---------------------------------------------------------------------------

def test_value_outlier_detected():
    rows = [_make_row("2022-01-03", 90, 110, 85, 100)]  # all < 1000
    data = {"1d": _make_df(rows)}
    data.update(_empty_intraday())
    result = validate_data(data)
    assert result["value_outliers"] > 0
    assert result["passed"] is False


# ---------------------------------------------------------------------------
# Range outlier: High-Low > 10% of Close
# ---------------------------------------------------------------------------

def test_range_outlier_detected():
    # Range = 5000, Close = 38000, range_pct ~ 13.2% > 10%
    rows = [_make_row("2022-01-03", 38000, 41000, 36000, 38000)]
    data = {"1d": _make_df(rows)}
    data.update(_empty_intraday())
    result = validate_data(data)
    assert len(result["range_outliers"]) == 1


# ---------------------------------------------------------------------------
# Clean data passes
# ---------------------------------------------------------------------------

def test_clean_data_passes():
    result = validate_data(_clean_data())
    assert result["ohlc_violations"] == 0
    assert result["value_outliers"] == 0
    assert result["passed"] is True


# ---------------------------------------------------------------------------
# Missing intraday: days in 1d with no intraday rows
# ---------------------------------------------------------------------------

def test_missing_intraday_flagged():
    daily_rows = [_make_row("2022-01-03", 38000, 38500, 37800, 38200)]
    data = {"1d": _make_df(daily_rows)}
    data.update(_empty_intraday())
    result = validate_data(data)
    assert "2022-01-03" in result["missing_intraday"]


def test_missing_intraday_not_flagged_when_present():
    daily_rows = [_make_row("2022-01-03", 38000, 38500, 37800, 38200)]
    intraday_rows = [_make_row("2022-01-03", 38000, 38300, 37900, 38100, "09:15")]
    data = {"1d": _make_df(daily_rows)}
    data.update(_empty_intraday())
    data["1h"] = _make_df(intraday_rows)
    result = validate_data(data)
    assert "2022-01-03" not in result["missing_intraday"]
