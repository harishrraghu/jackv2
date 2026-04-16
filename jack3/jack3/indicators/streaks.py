"""
Consecutive Day Streak counter.

Counts consecutive bullish (Close > Open) and bearish days.
Resets to 0 on reversal. Used by the Streak Fade strategy.
"""

import pandas as pd
import numpy as np

METADATA = {
    "name": "streaks",
    "display_name": "Consecutive Day Counter",
    "params": {},
    "output_columns": ["Bull_Streak", "Bear_Streak"],
    "timeframes": ["1d"],
}


def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """
    Compute consecutive bullish/bearish day streaks.

    Bull_Streak: count of consecutive days where Close > Open, resets on bearish.
    Bear_Streak: count of consecutive days where Close <= Open, resets on bullish.

    Example: B, B, B, Bear → Bull_Streak = [1,2,3,0], Bear_Streak = [0,0,0,1]

    Args:
        df: DataFrame with OHLC data.

    Returns:
        Copy of DataFrame with Bull_Streak and Bear_Streak columns.
    """
    df = df.copy()

    if len(df) == 0:
        df["Bull_Streak"] = pd.Series(dtype=int)
        df["Bear_Streak"] = pd.Series(dtype=int)
        return df

    bullish = (df["Close"] > df["Open"]).values
    bull_streak = np.zeros(len(df), dtype=int)
    bear_streak = np.zeros(len(df), dtype=int)

    for i in range(len(df)):
        if bullish[i]:
            bull_streak[i] = (bull_streak[i - 1] + 1) if i > 0 else 1
            bear_streak[i] = 0
        else:
            bull_streak[i] = 0
            bear_streak[i] = (bear_streak[i - 1] + 1) if i > 0 else 1

    df["Bull_Streak"] = bull_streak
    df["Bear_Streak"] = bear_streak

    return df
