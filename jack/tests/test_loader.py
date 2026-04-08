"""Tests for jack/data/loader.py using in-memory CSV data."""

from __future__ import annotations

import io
import sys
import os

import pandas as pd

# Allow importing from the jack package root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.loader import (
    OHLC_COLS,
    _clean_dataframe,
    get_daily_iterator,
    get_lookback,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_CSV = """\
Instrument,Date,Time,Open,High,Low,Close
BANKNIFTY,01-01-2021,9:15:00,30000,30100,29900,30050
BANKNIFTY,01-01-2021,9:30:00,30050,30200,30000,30150
BANKNIFTY,02-01-2021,9:15:00,30150,30250,30100,30200
BANKNIFTY,03-01-2021,9:15:00,29000,29000,29000,29000
BANKNIFTY,03-01-2021,9:30:00,29100,29300,29050,29250
"""


def _load_from_string(csv_text: str) -> pd.DataFrame:
    """Parse a CSV string through the production cleaning pipeline (minus file I/O)."""
    df = pd.read_csv(io.StringIO(csv_text), dtype={"Time": str}, parse_dates=["Date"], dayfirst=True)
    return _clean_dataframe(df)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLoadTimeframe:
    def test_basic_load(self):
        df = _load_from_string(SAMPLE_CSV)
        assert not df.empty
        assert list(df.columns[:6]) == ["Instrument", "Date", "Time", "Open", "High", "Low"]

    def test_ohlc_dtype(self):
        df = _load_from_string(SAMPLE_CSV)
        for col in OHLC_COLS:
            assert df[col].dtype == "float64", f"{col} should be float64"

    def test_computed_columns_present(self):
        df = _load_from_string(SAMPLE_CSV)
        for col in ["Range", "Body", "Return_pct", "Bullish"]:
            assert col in df.columns

    def test_range_equals_high_minus_low(self):
        df = _load_from_string(SAMPLE_CSV)
        pd.testing.assert_series_equal(
            df["Range"], (df["High"] - df["Low"]), check_names=False
        )

    def test_return_pct_calculation(self):
        df = _load_from_string(SAMPLE_CSV)
        expected = (df["Close"] - df["Open"]) / df["Open"] * 100
        pd.testing.assert_series_equal(df["Return_pct"], expected, check_names=False)

    def test_sorted_by_date_then_time(self):
        df = _load_from_string(SAMPLE_CSV)
        dates = df["Date"].tolist()
        times = df["Time"].tolist()
        for i in range(len(dates) - 1):
            assert (dates[i], times[i]) <= (dates[i + 1], times[i + 1])

    def test_date_parsed_as_datetime(self):
        df = _load_from_string(SAMPLE_CSV)
        assert pd.api.types.is_datetime64_any_dtype(df["Date"])

    def test_time_kept_as_string(self):
        df = _load_from_string(SAMPLE_CSV)
        assert df["Time"].dtype == object


class TestPlaceholderFiltering:
    def test_high_equals_low_rows_dropped(self):
        df = _load_from_string(SAMPLE_CSV)
        # Row with Date=03-01-2021 9:15 has H==L==29000 — should be dropped
        filtered = df[df["Date"] == pd.Timestamp("2021-01-03")]
        # Only the 9:30 row (non-placeholder) should remain
        assert len(filtered) == 1
        assert filtered.iloc[0]["Time"] == "9:30:00"

    def test_all_placeholder_rows_removed(self):
        placeholder_csv = """\
Instrument,Date,Time,Open,High,Low,Close
BANKNIFTY,01-01-2000,9:15:00,5000,5000,5000,5000
BANKNIFTY,02-01-2000,9:15:00,5000,5000,5000,5000
"""
        df = _load_from_string(placeholder_csv)
        assert df.empty

    def test_valid_rows_not_dropped(self):
        df = _load_from_string(SAMPLE_CSV)
        # Total rows: 4 valid (2 on 01-01, 1 on 02-01, 1 on 03-01 after filtering)
        assert len(df) == 4

    def test_nan_rows_dropped(self):
        nan_csv = """\
Instrument,Date,Time,Open,High,Low,Close
BANKNIFTY,01-01-2021,9:15:00,30000,30100,29900,
BANKNIFTY,01-01-2021,9:30:00,30050,30200,30000,30150
"""
        df = _load_from_string(nan_csv)
        assert len(df) == 1


class TestDailyIterator:
    def _make_data(self) -> dict[str, pd.DataFrame]:
        daily_csv = """\
Instrument,Date,Time,Open,High,Low,Close
BANKNIFTY,01-01-2021,15:30:00,30000,30200,29900,30150
BANKNIFTY,02-01-2021,15:30:00,30150,30300,30050,30200
BANKNIFTY,03-01-2021,15:30:00,29000,29300,28900,29250
"""
        m1_csv = """\
Instrument,Date,Time,Open,High,Low,Close
BANKNIFTY,01-01-2021,9:15:00,30000,30050,29990,30040
BANKNIFTY,02-01-2021,9:15:00,30150,30200,30100,30180
"""
        daily_df = _load_from_string(daily_csv)
        m1_df = _load_from_string(m1_csv)
        return {
            "1d": daily_df,
            "2h": pd.DataFrame(),
            "1h": pd.DataFrame(),
            "15m": pd.DataFrame(),
            "5m": pd.DataFrame(),
            "1m": m1_df,
        }

    def test_yields_correct_number_of_days(self):
        data = self._make_data()
        days = list(get_daily_iterator(data, "2021-01-01", "2021-01-03"))
        assert len(days) == 3

    def test_dates_are_timestamps(self):
        data = self._make_data()
        for day in get_daily_iterator(data, "2021-01-01", "2021-01-03"):
            assert isinstance(day["date"], pd.Timestamp)

    def test_correct_date_sequence(self):
        data = self._make_data()
        days = list(get_daily_iterator(data, "2021-01-01", "2021-01-03"))
        dates = [d["date"] for d in days]
        assert dates == sorted(dates)
        assert dates[0] == pd.Timestamp("2021-01-01")
        assert dates[-1] == pd.Timestamp("2021-01-03")

    def test_missing_intraday_yields_empty_df(self):
        data = self._make_data()
        days = list(get_daily_iterator(data, "2021-01-01", "2021-01-03"))
        # Day 3 has no 1m data
        day3 = next(d for d in days if d["date"] == pd.Timestamp("2021-01-03"))
        assert day3["1m"].empty

    def test_present_intraday_not_empty(self):
        data = self._make_data()
        days = list(get_daily_iterator(data, "2021-01-01", "2021-01-03"))
        day1 = next(d for d in days if d["date"] == pd.Timestamp("2021-01-01"))
        assert not day1["1m"].empty

    def test_date_range_filtering(self):
        data = self._make_data()
        days = list(get_daily_iterator(data, "2021-01-02", "2021-01-02"))
        assert len(days) == 1
        assert days[0]["date"] == pd.Timestamp("2021-01-02")

    def test_all_timeframe_keys_present(self):
        data = self._make_data()
        for day in get_daily_iterator(data, "2021-01-01", "2021-01-01"):
            for key in ["date", "daily", "2h", "1h", "15m", "5m", "1m"]:
                assert key in day


class TestGetLookback:
    def _make_data(self) -> dict[str, pd.DataFrame]:
        csv = """\
Instrument,Date,Time,Open,High,Low,Close
BANKNIFTY,01-01-2021,9:15:00,30000,30100,29900,30050
BANKNIFTY,02-01-2021,9:15:00,30050,30200,30000,30150
BANKNIFTY,03-01-2021,9:15:00,30150,30250,30100,30200
BANKNIFTY,04-01-2021,9:15:00,30200,30350,30150,30300
BANKNIFTY,05-01-2021,9:15:00,30300,30400,30200,30350
"""
        df = _load_from_string(csv)
        return {"1d": df}

    def test_excludes_current_date(self):
        data = self._make_data()
        current = pd.Timestamp("2021-01-04")
        result = get_lookback(data, current, n_days=10)
        for tf, df in result.items():
            assert (df["Date"] >= current).sum() == 0, f"{tf} contains data on/after current_date"

    def test_n_days_limit(self):
        data = self._make_data()
        current = pd.Timestamp("2021-01-05")
        result = get_lookback(data, current, n_days=2)
        unique_dates = result["1d"]["Date"].unique()
        assert len(unique_dates) == 2

    def test_returns_all_timeframes(self):
        csv = """\
Instrument,Date,Time,Open,High,Low,Close
BANKNIFTY,01-01-2021,9:15:00,30000,30100,29900,30050
"""
        df = _load_from_string(csv)
        data = {"1d": df, "1m": df.copy()}
        current = pd.Timestamp("2021-01-02")
        result = get_lookback(data, current, n_days=5)
        assert set(result.keys()) == {"1d", "1m"}

    def test_strictly_before_current_date(self):
        data = self._make_data()
        current = pd.Timestamp("2021-01-03")
        result = get_lookback(data, current, n_days=10)
        assert pd.Timestamp("2021-01-03") not in result["1d"]["Date"].values
        assert pd.Timestamp("2021-01-04") not in result["1d"]["Date"].values

    def test_no_data_before_current_date(self):
        data = self._make_data()
        current = pd.Timestamp("2020-12-31")
        result = get_lookback(data, current, n_days=5)
        assert result["1d"].empty
