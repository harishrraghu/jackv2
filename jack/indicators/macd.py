"""
MACD (Moving Average Convergence Divergence) indicator.

MACD Line = EMA(fast) - EMA(slow) of Close
Signal Line = EMA(signal) of MACD Line
Histogram = MACD - Signal
"""

import pandas as pd
import numpy as np

METADATA = {
    "name": "macd",
    "display_name": "MACD",
    "params": {"fast": 12, "slow": 26, "signal": 9},
    "output_columns": ["MACD", "MACD_Signal", "MACD_Hist"],
    "timeframes": ["1d", "2h", "1h", "15m", "5m"],
}


def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """
    Compute MACD, Signal, and Histogram.

    Args:
        df: DataFrame with OHLC data.
        fast: Fast EMA period (default: 12).
        slow: Slow EMA period (default: 26).
        signal: Signal line EMA period (default: 9).

    Returns:
        Copy of DataFrame with MACD, MACD_Signal, MACD_Hist columns.
    """
    df = df.copy()
    fast = params.get("fast", METADATA["params"]["fast"])
    slow = params.get("slow", METADATA["params"]["slow"])
    signal = params.get("signal", METADATA["params"]["signal"])

    min_required = slow + signal
    if len(df) < min_required:
        df["MACD"] = np.nan
        df["MACD_Signal"] = np.nan
        df["MACD_Hist"] = np.nan
        return df

    ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()

    df["MACD"] = ema_fast - ema_slow
    df["MACD_Signal"] = df["MACD"].ewm(span=signal, adjust=False).mean()
    df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]

    return df
