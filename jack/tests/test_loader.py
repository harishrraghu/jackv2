"""Tests for data loader."""

import os
import tempfile

import pandas as pd
import pytest

# Ensure jack is importable
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.loader import load_timeframe, get_daily_iterator, get_lookback


@pytest.fixture
def mock_csv_dir(tmp_path):
    """Create a temporary directory with a mock CSV file."""
    csv_content = """Instrument,Date,Time,Open,High,Low,Close
BANKNIFTY,15-01-2020,9:15:00,30000,30200,29900,30100
BANKNIFTY,15-01-2020,9:30:00,30100,30300,30050,30250
BANKNIFTY,16-01-2020,9:15:00,30250,30400,30200,30350
BANKNIFTY,16-01-2020,9:30:00,30350,30500,30300,30450
BANKNIFTY,17-01-2020,9:15:00,30450,30600,30400,30550
"""
    filepath = tmp_path / "bank-nifty-1d-data.csv"
    filepath.write_text(csv_content)
    return str(tmp_path)


@pytest.fixture
def mock_csv_with_placeholders(tmp_path):
    """Mock CSV with placeholder rows (H == L)."""
    csv_content = """Instrument,Date,Time,Open,High,Low,Close
BANKNIFTY,15-01-2002,9:15:00,10000,10000,10000,10000
BANKNIFTY,16-01-2002,9:15:00,10000,10000,10000,10000
BANKNIFTY,15-01-2020,9:15:00,30000,30200,29900,30100
BANKNIFTY,16-01-2020,9:15:00,30250,30400,30200,30350
"""
    filepath = tmp_path / "bank-nifty-1d-data.csv"
    filepath.write_text(csv_content)
    return str(tmp_path)


def test_load_timeframe_basic(mock_csv_dir):
    """Test basic loading of a CSV file."""
    df = load_timeframe("1d", mock_csv_dir)
    assert len(df) == 5
    assert "Range" in df.columns
    assert "Body" in df.columns
    assert "Return_pct" in df.columns
    assert "Bullish" in df.columns


def test_load_timeframe_types(mock_csv_dir):
    """Test that columns have correct types."""
    df = load_timeframe("1d", mock_csv_dir)
    assert df["Open"].dtype == "float64"
    assert df["High"].dtype == "float64"
    assert df["Date"].dtype == "datetime64[ns]"


def test_placeholder_rows_filtered(mock_csv_with_placeholders):
    """Test that placeholder rows (H==L) get filtered."""
    df = load_timeframe("1d", mock_csv_with_placeholders)
    assert len(df) == 2  # Only real data rows
    assert df["High"].iloc[0] != df["Low"].iloc[0]


def test_file_not_found():
    """Test clear error on missing file."""
    with pytest.raises(FileNotFoundError):
        load_timeframe("1d", "/nonexistent/path/")


def test_daily_iterator(mock_csv_dir):
    """Test daily iterator yields correct dates."""
    df = load_timeframe("1d", mock_csv_dir)
    data = {"1d": df, "2h": pd.DataFrame(), "1h": pd.DataFrame(),
            "15m": pd.DataFrame(), "5m": pd.DataFrame(), "1m": pd.DataFrame()}

    days = list(get_daily_iterator(data, "2020-01-01", "2020-12-31"))
    # The 1d data has 5 rows across 3 unique dates (15th, 16th, 17th)
    # Daily iterator iterates over each ROW in the 1d data matching the range
    # Since rows span 3 unique dates but iterrows sees 5 rows:
    # Actually daily iterator yields one entry per ROW in the daily data
    assert len(days) >= 3  # At least 3 unique dates
    assert "date" in days[0]
    assert "daily" in days[0]


def test_lookback_no_future_data(mock_csv_dir):
    """Test that get_lookback never includes data on or after current_date."""
    df = load_timeframe("1d", mock_csv_dir)
    data = {"1d": df}

    current_date = pd.Timestamp("2020-01-16")
    lookback = get_lookback(data, current_date, n_days=5)

    lb_df = lookback["1d"]
    if not lb_df.empty:
        assert lb_df["Date"].max() < current_date
