"""
Supertrend indicator.

Popular Indian market indicator that flips between upper and lower bands
based on close price crossover of ATR-based bands. Gives clear
bullish/bearish trend signals.

Direction: 1 = bullish (price above supertrend), -1 = bearish.
"""

import pandas as pd
import numpy as np

METADATA = {
    "name": "supertrend",
    "display_name": "Supertrend",
    "params": {"period": 10, "multiplier": 3.0},
    "output_columns": ["Supertrend", "Supertrend_Direction"],
    "timeframes": ["1d", "2h", "1h", "15m", "5m"],
}


def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """
    Compute Supertrend indicator.

    Uses ATR-based upper/lower bands that flip based on close price crossover.

    Args:
        df: DataFrame with OHLC data.
        period: ATR period (default: 10).
        multiplier: ATR multiplier for band width (default: 3.0).

    Returns:
        Copy of DataFrame with Supertrend and Supertrend_Direction columns.
    """
    df = df.copy()
    period = params.get("period", METADATA["params"]["period"])
    multiplier = params.get("multiplier", METADATA["params"]["multiplier"])

    if len(df) < period:
        df["Supertrend"] = np.nan
        df["Supertrend_Direction"] = np.nan
        return df

    # True Range
    high = df["High"].values
    low = df["Low"].values
    close = df["Close"].values

    tr = np.zeros(len(df))
    tr[0] = high[0] - low[0]
    for i in range(1, len(df)):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )

    # ATR using rolling mean
    atr = pd.Series(tr).rolling(window=period).mean().values

    # Basic upper and lower bands
    hl2 = (high + low) / 2
    basic_upper = hl2 + multiplier * atr
    basic_lower = hl2 - multiplier * atr

    # Supertrend calculation
    supertrend = np.full(len(df), np.nan)
    direction = np.full(len(df), np.nan)

    # Final upper and lower bands with adjustment
    final_upper = np.copy(basic_upper)
    final_lower = np.copy(basic_lower)

    for i in range(period, len(df)):
        if i == period:
            # Initial direction based on close vs bands
            if close[i] <= final_upper[i]:
                supertrend[i] = final_upper[i]
                direction[i] = -1
            else:
                supertrend[i] = final_lower[i]
                direction[i] = 1
            continue

        # Adjust upper band
        if basic_upper[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]:
            final_upper[i] = basic_upper[i]
        else:
            final_upper[i] = final_upper[i - 1]

        # Adjust lower band
        if basic_lower[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]:
            final_lower[i] = basic_lower[i]
        else:
            final_lower[i] = final_lower[i - 1]

        # Determine direction
        if direction[i - 1] == 1:  # Was bullish
            if close[i] < final_lower[i]:
                direction[i] = -1
                supertrend[i] = final_upper[i]
            else:
                direction[i] = 1
                supertrend[i] = final_lower[i]
        else:  # Was bearish
            if close[i] > final_upper[i]:
                direction[i] = 1
                supertrend[i] = final_lower[i]
            else:
                direction[i] = -1
                supertrend[i] = final_upper[i]

    df["Supertrend"] = supertrend
    df["Supertrend_Direction"] = direction

    return df
