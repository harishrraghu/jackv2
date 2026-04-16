"""
Opening Range Breakout (ORB) indicator.

Extracts the first 15-minute candle of the trading day (9:15).
Used as the opening range for breakout and gap-fill strategies.

NOTE: This indicator has a different signature — it takes the 15m DataFrame
for a single day and returns a single-row result dict. The compute() function
also works on multi-day DataFrames by extracting the first candle per day.
"""

import pandas as pd
import numpy as np

METADATA = {
    "name": "orb",
    "display_name": "Opening Range (First 15-min)",
    "params": {},
    "output_columns": ["ORB_High", "ORB_Low", "ORB_Range", "ORB_Bullish"],
    "timeframes": ["15m"],
}


def compute_single_day(day_15m: pd.DataFrame) -> dict:
    """
    Extract ORB values from a single day's 15m data.

    Args:
        day_15m: DataFrame of 15m candles for one day.

    Returns:
        Dict with ORB_High, ORB_Low, ORB_Range, ORB_Bullish.
        Returns NaN values if no data available.
    """
    if day_15m.empty:
        return {
            "ORB_High": np.nan,
            "ORB_Low": np.nan,
            "ORB_Range": np.nan,
            "ORB_Bullish": False,
        }

    # Get the first candle (earliest time, should be 9:15)
    first_candle = day_15m.iloc[0]

    orb_high = float(first_candle["High"])
    orb_low = float(first_candle["Low"])

    return {
        "ORB_High": orb_high,
        "ORB_Low": orb_low,
        "ORB_Range": orb_high - orb_low,
        "ORB_Bullish": bool(first_candle["Close"] > first_candle["Open"]),
    }


def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """
    Compute ORB for each day in the 15m DataFrame.

    Takes the first candle of each day (earliest Time) and extracts the
    opening range values. All subsequent candles for the same day get
    the same ORB values.

    Args:
        df: DataFrame with 15m OHLC data (must have Date column).

    Returns:
        Copy of DataFrame with ORB columns.
    """
    df = df.copy()

    if df.empty:
        for col in ["ORB_High", "ORB_Low", "ORB_Range", "ORB_Bullish"]:
            df[col] = pd.Series(dtype=float if col != "ORB_Bullish" else bool)
        return df

    orb_values = {"ORB_High": [], "ORB_Low": [], "ORB_Range": [], "ORB_Bullish": []}

    for date in df["Date"].unique():
        day_data = df[df["Date"] == date].sort_values("Time")
        orb = compute_single_day(day_data)
        n_rows = len(day_data)
        for key in orb_values:
            orb_values[key].extend([orb[key]] * n_rows)

    for col, vals in orb_values.items():
        df[col] = vals

    return df
