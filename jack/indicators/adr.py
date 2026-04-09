"""
Average Daily Range (ADR) indicator.

Rolling mean of the daily High-Low range. ADR_Pct normalizes as a
percentage of close for cross-period comparison.
"""

import pandas as pd
import numpy as np

METADATA = {
    "name": "adr",
    "display_name": "Average Daily Range",
    "params": {"period": 20},
    "output_columns": ["ADR", "ADR_Pct"],
    "timeframes": ["1d"],
}


def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """
    Compute ADR and ADR_Pct on daily data.

    ADR = rolling mean of (High - Low) over period
    ADR_Pct = ADR / Close * 100

    Args:
        df: DataFrame with daily OHLC data.
        period: Rolling period (default: 20).

    Returns:
        Copy of DataFrame with ADR and ADR_Pct columns.
    """
    df = df.copy()
    period = params.get("period", METADATA["params"]["period"])

    if len(df) < period:
        df["ADR"] = np.nan
        df["ADR_Pct"] = np.nan
        return df

    daily_range = df["High"] - df["Low"]
    df["ADR"] = daily_range.rolling(window=period).mean()
    df["ADR_Pct"] = df["ADR"] / df["Close"] * 100

    return df
