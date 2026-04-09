"""
First Hour Summary indicator.

Summarizes the first trading hour (9:15-10:15) performance.
When the first hour move exceeds 0.4%, it predicts the day's direction 79.7%.

NOTE: Like ORB, this takes a single day's 1h data and returns a single-row result.
The compute() function also works on multi-day DataFrames.
"""

import pandas as pd
import numpy as np

METADATA = {
    "name": "first_hour",
    "display_name": "First Hour Summary",
    "params": {},
    "output_columns": ["FH_Return", "FH_Range", "FH_Direction", "FH_Strong"],
    "timeframes": ["1h"],
}


def compute_single_day(day_1h: pd.DataFrame) -> dict:
    """
    Extract first hour summary from a single day's 1h data.

    Args:
        day_1h: DataFrame of 1h candles for one day.

    Returns:
        Dict with FH_Return, FH_Range, FH_Direction, FH_Strong.
    """
    if day_1h.empty:
        return {
            "FH_Return": np.nan,
            "FH_Range": np.nan,
            "FH_Direction": 0,
            "FH_Strong": False,
        }

    # Get the first candle (should be 9:15)
    first_candle = day_1h.iloc[0]

    fh_return = (first_candle["Close"] - first_candle["Open"]) / first_candle["Open"] * 100
    fh_range = first_candle["High"] - first_candle["Low"]

    if fh_return > 0:
        fh_direction = 1
    elif fh_return < 0:
        fh_direction = -1
    else:
        fh_direction = 0

    fh_strong = abs(fh_return) > 0.4

    return {
        "FH_Return": fh_return,
        "FH_Range": fh_range,
        "FH_Direction": fh_direction,
        "FH_Strong": fh_strong,
    }


def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """
    Compute first hour summary for each day in the 1h DataFrame.

    Takes the first candle of each day and computes the first hour metrics.
    All subsequent candles for the same day get the same values.

    Args:
        df: DataFrame with 1h OHLC data (must have Date column).

    Returns:
        Copy of DataFrame with FH columns.
    """
    df = df.copy()

    if df.empty:
        for col in ["FH_Return", "FH_Range", "FH_Direction", "FH_Strong"]:
            df[col] = pd.Series(dtype=float if col != "FH_Strong" else bool)
        return df

    fh_values = {"FH_Return": [], "FH_Range": [], "FH_Direction": [], "FH_Strong": []}

    for date in df["Date"].unique():
        day_data = df[df["Date"] == date].sort_values("Time")
        fh = compute_single_day(day_data)
        n_rows = len(day_data)
        for key in fh_values:
            fh_values[key].extend([fh[key]] * n_rows)

    for col, vals in fh_values.items():
        df[col] = vals

    return df
