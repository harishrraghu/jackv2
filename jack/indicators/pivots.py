"""
Classic Pivot Points indicator.

Computed from PREVIOUS day's High, Low, Close. Used as intraday
support/resistance levels. CRITICAL: uses previous row's HLC, not current.
"""

import pandas as pd
import numpy as np

METADATA = {
    "name": "pivots",
    "display_name": "Classic Pivot Points",
    "params": {},
    "output_columns": ["PP", "R1", "R2", "R3", "S1", "S2", "S3"],
    "timeframes": ["1d"],
}


def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """
    Compute classic pivot points from PREVIOUS day's HLC.

    PP = (H + L + C) / 3
    R1 = 2*PP - L,  S1 = 2*PP - H
    R2 = PP + (H-L), S2 = PP - (H-L)
    R3 = 2*PP - 2*L + H, S3 = 2*PP - 2*H + L

    Args:
        df: DataFrame with daily OHLC data.

    Returns:
        Copy of DataFrame with pivot columns (using previous row's HLC).
    """
    df = df.copy()

    cols = ["PP", "R1", "R2", "R3", "S1", "S2", "S3"]

    if len(df) < 2:
        for col in cols:
            df[col] = np.nan
        return df

    # Use PREVIOUS row's High, Low, Close
    prev_high = df["High"].shift(1)
    prev_low = df["Low"].shift(1)
    prev_close = df["Close"].shift(1)

    pp = (prev_high + prev_low + prev_close) / 3

    df["PP"] = pp
    df["R1"] = 2 * pp - prev_low
    df["S1"] = 2 * pp - prev_high
    df["R2"] = pp + (prev_high - prev_low)
    df["S2"] = pp - (prev_high - prev_low)
    df["R3"] = 2 * pp - 2 * prev_low + prev_high
    df["S3"] = 2 * pp - 2 * prev_high + prev_low

    return df
