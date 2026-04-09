"""
Simple Moving Average (SMA) indicator.

Computes a rolling arithmetic mean of the Close price over a fixed window.
"""

import pandas as pd
import numpy as np

METADATA = {
    "name": "sma",
    "display_name": "Simple Moving Average",
    "params": {"period": 20},
    "output_columns": ["SMA_{period}"],
    "timeframes": ["1d", "2h", "1h", "15m", "5m"],
}


def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """
    Compute SMA on Close prices.

    Args:
        df: DataFrame with OHLC data.
        period: SMA period (default: 20).

    Returns:
        Copy of DataFrame with SMA_{period} column appended.
    """
    df = df.copy()
    period = params.get("period", METADATA["params"]["period"])
    col_name = f"SMA_{period}"

    if len(df) < period:
        df[col_name] = np.nan
        return df

    df[col_name] = df["Close"].rolling(window=period).mean()
    return df
