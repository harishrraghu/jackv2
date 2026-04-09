"""
Gap Calculator indicator.

Measures the gap between today's Open and yesterday's Close.
Classifies gaps by size for strategy filtering.
"""

import pandas as pd
import numpy as np

METADATA = {
    "name": "gap",
    "display_name": "Gap Calculator",
    "params": {},
    "output_columns": ["Gap_Pts", "Gap_Pct", "Gap_Type"],
    "timeframes": ["1d"],
}


def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """
    Compute gap size and classification.

    Gap_Pts = today Open - yesterday Close
    Gap_Pct = Gap_Pts / yesterday Close * 100
    Gap_Type: "large_up" (>0.5%), "small_up" (0.1-0.5%),
              "flat" (-0.1 to 0.1%), "small_down" (-0.5 to -0.1%),
              "large_down" (<-0.5%)

    Args:
        df: DataFrame with daily OHLC data.

    Returns:
        Copy of DataFrame with Gap columns.
    """
    df = df.copy()

    if len(df) < 2:
        df["Gap_Pts"] = np.nan
        df["Gap_Pct"] = np.nan
        df["Gap_Type"] = "flat"
        return df

    prev_close = df["Close"].shift(1)
    df["Gap_Pts"] = df["Open"] - prev_close
    df["Gap_Pct"] = np.where(
        prev_close != 0,
        df["Gap_Pts"] / prev_close * 100,
        0,
    )

    # Classify gaps
    conditions = [
        df["Gap_Pct"] > 0.5,
        (df["Gap_Pct"] > 0.1) & (df["Gap_Pct"] <= 0.5),
        (df["Gap_Pct"] >= -0.1) & (df["Gap_Pct"] <= 0.1),
        (df["Gap_Pct"] >= -0.5) & (df["Gap_Pct"] < -0.1),
        df["Gap_Pct"] < -0.5,
    ]
    choices = ["large_up", "small_up", "flat", "small_down", "large_down"]

    df["Gap_Type"] = np.select(conditions, choices, default="flat")

    return df
