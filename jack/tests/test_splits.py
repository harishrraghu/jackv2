"""Tests for data splits and quarantine enforcement."""

import os
import sys
import tempfile

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.splits import DataSplits, DataLeakageError, validate_no_leakage


@pytest.fixture
def config_file(tmp_path):
    """Create a temporary config file."""
    config = """
data:
  base_path: "./data/raw/"
  timeframes: ["1d"]
  file_pattern: "bank-nifty-{timeframe}-data.csv"

splits:
  train:
    start: "2015-01-01"
    end: "2020-12-31"
  test:
    start: "2021-01-01"
    end: "2022-12-31"
  holdout:
    start: "2023-01-01"
    end: "2024-04-12"

trading:
  initial_capital: 1000000
market:
  lot_size: 15
"""
    filepath = tmp_path / "settings.yaml"
    filepath.write_text(config)
    return str(filepath)


def test_train_range(config_file):
    """Test train range returns correct dates."""
    splits = DataSplits(config_file)
    start, end = splits.get_train_range()
    assert start == "2015-01-01"
    assert end == "2020-12-31"


def test_test_range(config_file):
    """Test test range returns correct dates."""
    splits = DataSplits(config_file)
    start, end = splits.get_test_range()
    assert start == "2021-01-01"
    assert end == "2022-12-31"


def test_holdout_range(config_file):
    """Test holdout range."""
    splits = DataSplits(config_file)
    start, end = splits.get_holdout_range()
    assert start == "2023-01-01"
    assert end == "2024-04-12"


def test_leakage_detected_holdout_during_train(config_file):
    """Verify DataLeakageError is raised when accessing holdout during training."""
    splits = DataSplits(config_file)
    holdout_dates = [pd.Timestamp("2023-06-15")]

    with pytest.raises(DataLeakageError):
        validate_no_leakage("train", holdout_dates, splits=splits)


def test_no_leakage_valid_train(config_file):
    """Test that valid train dates pass."""
    splits = DataSplits(config_file)
    train_dates = [pd.Timestamp("2018-06-15"), pd.Timestamp("2020-01-01")]
    assert validate_no_leakage("train", train_dates, splits=splits) is True


def test_quarantine_boundary_exact(config_file):
    """Test exact boundary: last day of train, first day of test."""
    splits = DataSplits(config_file)

    # Last day of train — should pass
    assert validate_no_leakage(
        "train", [pd.Timestamp("2020-12-31")], splits=splits
    ) is True

    # First day of test — should fail during train
    with pytest.raises(DataLeakageError):
        validate_no_leakage(
            "train", [pd.Timestamp("2021-01-01")], splits=splits
        )


def test_accessible_range_test(config_file):
    """Test that test split can access all past data and test data."""
    splits = DataSplits(config_file)
    start, end = splits.get_accessible_range("test")
    assert start == "2000-01-01"  # All past data allowed
    assert end == "2022-12-31"


def test_past_lookback_allowed_during_train(config_file):
    """Past data (before train start) should NOT be flagged as leakage."""
    splits = DataSplits(config_file)
    past_dates = [pd.Timestamp("2014-06-15"), pd.Timestamp("2012-01-01")]
    assert validate_no_leakage("train", past_dates, splits=splits) is True
