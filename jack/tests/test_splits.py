"""Tests for data/splits.py — no real CSV files required."""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

# Allow running from the jack/ directory or its parent
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.splits import DataLeakageError, DataSplits, validate_no_leakage

# Path to settings.yaml relative to the jack/ directory
_CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "settings.yaml")


class TestDataSplitsRanges:
    def setup_method(self):
        self.ds = DataSplits(config_path=_CONFIG)

    def test_train_range(self):
        assert self.ds.get_train_range() == ("2015-01-01", "2020-12-31")

    def test_test_range(self):
        assert self.ds.get_test_range() == ("2021-01-01", "2022-12-31")

    def test_holdout_range(self):
        assert self.ds.get_holdout_range() == ("2023-01-01", "2024-04-12")


class TestValidateNoLeakage:
    # --- train split ---

    def test_train_valid_dates_pass(self):
        dates = [pd.Timestamp("2015-01-01"), pd.Timestamp("2018-06-15"), pd.Timestamp("2020-12-31")]
        assert validate_no_leakage("train", dates) is True

    def test_train_last_valid_date_passes(self):
        # 2020-12-31 is the exact boundary — must pass
        assert validate_no_leakage("train", [pd.Timestamp("2020-12-31")]) is True

    def test_train_next_day_raises(self):
        # 2021-01-01 is one day past train end — must raise
        with pytest.raises(DataLeakageError) as exc_info:
            validate_no_leakage("train", [pd.Timestamp("2021-01-01")])
        assert "2021-01-01" in str(exc_info.value)
        assert "train" in str(exc_info.value)

    def test_train_holdout_date_raises(self):
        # Accessing a holdout date during training is leakage
        with pytest.raises(DataLeakageError) as exc_info:
            validate_no_leakage("train", [pd.Timestamp("2023-01-15")])
        assert "2023-01-15" in str(exc_info.value)
        assert "train" in str(exc_info.value)

    def test_train_error_message_format(self):
        """Error must mention the exact date and the train boundary dates."""
        with pytest.raises(DataLeakageError) as exc_info:
            validate_no_leakage("train", [pd.Timestamp("2023-01-15")])
        msg = str(exc_info.value)
        assert "2015-01-01" in msg
        assert "2020-12-31" in msg

    # --- test split ---

    def test_test_allows_train_dates(self):
        # test split may look back into train data (cumulative)
        dates = [pd.Timestamp("2015-01-01"), pd.Timestamp("2022-12-31")]
        assert validate_no_leakage("test", dates) is True

    def test_test_last_valid_date_passes(self):
        assert validate_no_leakage("test", [pd.Timestamp("2022-12-31")]) is True

    def test_test_next_day_raises(self):
        with pytest.raises(DataLeakageError):
            validate_no_leakage("test", [pd.Timestamp("2023-01-01")])

    def test_test_holdout_date_raises(self):
        with pytest.raises(DataLeakageError):
            validate_no_leakage("test", [pd.Timestamp("2023-06-01")])

    # --- holdout split ---

    def test_holdout_allows_all_prior_data(self):
        dates = [pd.Timestamp("2015-01-01"), pd.Timestamp("2022-12-31"), pd.Timestamp("2024-04-12")]
        assert validate_no_leakage("holdout", dates) is True

    def test_holdout_beyond_end_raises(self):
        with pytest.raises(DataLeakageError):
            validate_no_leakage("holdout", [pd.Timestamp("2024-04-13")])

    # --- edge cases ---

    def test_empty_date_list_passes(self):
        assert validate_no_leakage("train", []) is True

    def test_unknown_split_raises_value_error(self):
        with pytest.raises(ValueError):
            validate_no_leakage("unknown", [pd.Timestamp("2020-01-01")])

    def test_first_violating_date_mentioned_in_error(self):
        dates = [pd.Timestamp("2019-01-01"), pd.Timestamp("2023-01-15"), pd.Timestamp("2019-06-01")]
        with pytest.raises(DataLeakageError) as exc_info:
            validate_no_leakage("train", dates)
        assert "2023-01-15" in str(exc_info.value)
