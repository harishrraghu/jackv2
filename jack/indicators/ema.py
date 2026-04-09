"""
Exponential Moving Average (EMA) indicator.

Computes an exponentially-weighted moving average of the Close price.
Faster-reacting than SMA, giving more weight to recent prices.
"""

import pandas as pd
import numpy as np

METADATA = {
    "name": "ema",
    "display_name": "Exponential Moving Average",
    "params": {"period": 9},
    "output_columns": ["EMA_{period}"],
    "timeframes": ["1d", "2h", "1h", "15m", "5m"],
}


def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """
    Compute EMA on Close prices.

    Args:
        df: DataFrame with at minimum Date, Open, High, Low, Close columns.
        period: EMA period (default: 9).

    Returns:
        Copy of DataFrame with EMA_{period} column appended.
    """
    df = df.copy()
    period = params.get("period", METADATA["params"]["period"])
    col_name = f"EMA_{period}"

    if len(df) < period:
        df[col_name] = np.nan
        return df

    df[col_name] = df["Close"].ewm(span=period, adjust=False).mean()
    return df
