"""Tests for oscillator indicators (RSI, Stochastic, ATR, Bollinger Bands)."""

import os
import sys

import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indicators.rsi import compute as rsi_compute
from indicators.stochastic import compute as stoch_compute
from indicators.atr import compute as atr_compute
from indicators.bbands import compute as bb_compute


def _make_ohlc(n=30, base=30000, trend=10):
    """Create a mock OHLC DataFrame."""
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


class TestRSI:
    def test_basic(self):
        df = _make_ohlc(30)
        result = rsi_compute(df)
        assert "RSI" in result.columns

    def test_all_up_rsi_high(self):
        """When all closes go up, RSI should approach 100."""
        df = _make_ohlc(30, trend=50)
        result = rsi_compute(df, period=14)
        last_rsi = result["RSI"].dropna().iloc[-1]
        assert last_rsi > 70

    def test_all_down_rsi_low(self):
        """When all closes go down, RSI should approach 0."""
        df = _make_ohlc(30, trend=-50)
        result = rsi_compute(df, period=14)
        last_rsi = result["RSI"].dropna().iloc[-1]
        assert last_rsi < 30


class TestStochastic:
    def test_basic(self):
        df = _make_ohlc(30)
        result = stoch_compute(df)
        assert "Stoch_K" in result.columns
        assert "Stoch_D" in result.columns

    def test_at_period_high(self):
        """When Close is at period high, %K should be 100."""
        df = _make_ohlc(30, trend=100)  # Strong uptrend
        result = stoch_compute(df, k_period=14)
        last_k = result["Stoch_K"].dropna().iloc[-1]
        assert last_k > 90  # Should be near 100


class TestATR:
    def test_basic(self):
        df = _make_ohlc(30)
        result = atr_compute(df, period=14)
        assert "ATR" in result.columns
        assert "ATR_Pct" in result.columns

    def test_constant_range(self):
        """For constant-range series, ATR should equal that range."""
        n = 30
        dates = pd.date_range("2020-01-01", periods=n)
        data = {
            "Date": dates,
            "Open": [30000] * n,
            "High": [30200] * n,
            "Low": [29800] * n,
            "Close": [30100] * n,
            "Time": ["9:15:00"] * n,
        }
        df = pd.DataFrame(data)
        result = atr_compute(df, period=14)
        last_atr = result["ATR"].dropna().iloc[-1]
        assert abs(last_atr - 400) < 10  # Range is 200 (H-L) but TR considers prev close


class TestBollingerBands:
    def test_basic(self):
        df = _make_ohlc(30)
        result = bb_compute(df, period=20)
        for col in ["BB_Upper", "BB_Mid", "BB_Lower", "BB_Width", "BB_Pct"]:
            assert col in result.columns

    def test_bb_pct_at_mid(self):
        """When Close == BB_Mid, BB_Pct should be ~0.5."""
        df = _make_ohlc(30, trend=0)  # Flat price
        result = bb_compute(df, period=20)
        bb_pct = result["BB_Pct"].dropna()
        if len(bb_pct) > 0:
            last_pct = bb_pct.iloc[-1]
            # Flat price means close = mid, so BB_Pct ≈ 0.5
            assert 0.3 < last_pct < 0.7
