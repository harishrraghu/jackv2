"""Tests for trend indicators (EMA, SMA, MACD, Supertrend)."""

import os
import sys

import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indicators.ema import compute as ema_compute
from indicators.sma import compute as sma_compute
from indicators.macd import compute as macd_compute
from indicators.supertrend import compute as supertrend_compute


def _make_ohlc(n=30, base=30000, trend=10):
    """Create a mock OHLC DataFrame with n rows."""
    dates = pd.date_range("2020-01-01", periods=n)
    closes = [base + i * trend for i in range(n)]
    data = {
        "Date": dates,
        "Open": [c - 50 for c in closes],
        "High": [c + 100 for c in closes],
        "Low": [c - 100 for c in closes],
        "Close": closes,
        "Time": ["9:15:00"] * n,
    }
    return pd.DataFrame(data)


class TestEMA:
    def test_basic(self):
        df = _make_ohlc(30)
        result = ema_compute(df, period=9)
        assert "EMA_9" in result.columns
        assert not result["EMA_9"].isna().all()

    def test_edge_case_short_df(self):
        df = _make_ohlc(3)
        result = ema_compute(df, period=9)
        assert "EMA_9" in result.columns
        assert result["EMA_9"].isna().all()

    def test_no_side_effects(self):
        df = _make_ohlc(30)
        original_cols = list(df.columns)
        ema_compute(df, period=9)
        assert list(df.columns) == original_cols  # Input not modified

    def test_dynamic_column_naming(self):
        df = _make_ohlc(30)
        result = ema_compute(df, period=21)
        assert "EMA_21" in result.columns


class TestSMA:
    def test_basic(self):
        df = _make_ohlc(30)
        result = sma_compute(df, period=20)
        assert "SMA_20" in result.columns

    def test_edge_case_short_df(self):
        df = _make_ohlc(5)
        result = sma_compute(df, period=20)
        assert result["SMA_20"].isna().all()


class TestMACD:
    def test_basic(self):
        df = _make_ohlc(50)
        result = macd_compute(df)
        assert "MACD" in result.columns
        assert "MACD_Signal" in result.columns
        assert "MACD_Hist" in result.columns

    def test_edge_case_short(self):
        df = _make_ohlc(10)
        result = macd_compute(df)
        assert result["MACD"].isna().all()


class TestSupertrend:
    def test_basic(self):
        df = _make_ohlc(30)
        result = supertrend_compute(df, period=10, multiplier=3.0)
        assert "Supertrend" in result.columns
        assert "Supertrend_Direction" in result.columns

    def test_trending_up_direction(self):
        """In a clear uptrend, Supertrend should be mostly bullish (1)."""
        df = _make_ohlc(50, base=30000, trend=50)  # Strong uptrend
        result = supertrend_compute(df, period=10, multiplier=2.0)
        directions = result["Supertrend_Direction"].dropna()
        if len(directions) > 0:
            bullish_pct = (directions == 1).sum() / len(directions)
            assert bullish_pct > 0.5  # Should be mostly bullish

    def test_edge_case_short(self):
        df = _make_ohlc(5)
        result = supertrend_compute(df, period=10)
        assert result["Supertrend"].isna().all()
