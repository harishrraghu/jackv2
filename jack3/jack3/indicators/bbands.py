"""
Bollinger Bands indicator.

Volatility bands placed above and below a moving average. Width reflects
market volatility. BB_Pct shows where price sits within the bands.
"""

import pandas as pd
import numpy as np

METADATA = {
    "name": "bbands",
    "display_name": "Bollinger Bands",
    "params": {"period": 20, "std_dev": 2.0},
    "output_columns": ["BB_Upper", "BB_Mid", "BB_Lower", "BB_Width", "BB_Pct"],
    "timeframes": ["1d", "2h", "1h", "15m", "5m"],
}


def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """
    Compute Bollinger Bands.

    BB_Mid = SMA(period) of Close
    BB_Upper = BB_Mid + std_dev * rolling std
    BB_Lower = BB_Mid - std_dev * rolling std
    BB_Width = (Upper - Lower) / Mid * 100
    BB_Pct = (Close - Lower) / (Upper - Lower) — position within bands

    Args:
        df: DataFrame with OHLC data.
        period: SMA period (default: 20).
        std_dev: Standard deviation multiplier (default: 2.0).

    Returns:
        Copy of DataFrame with BB columns.
    """
    df = df.copy()
    period = params.get("period", METADATA["params"]["period"])
    std_dev = params.get("std_dev", METADATA["params"]["std_dev"])

    if len(df) < period:
        for col in ["BB_Upper", "BB_Mid", "BB_Lower", "BB_Width", "BB_Pct"]:
            df[col] = np.nan
        return df

    df["BB_Mid"] = df["Close"].rolling(window=period).mean()
    rolling_std = df["Close"].rolling(window=period).std()

    df["BB_Upper"] = df["BB_Mid"] + std_dev * rolling_std
    df["BB_Lower"] = df["BB_Mid"] - std_dev * rolling_std

    # Width as percentage of mid
    df["BB_Width"] = np.where(
        df["BB_Mid"] != 0,
        (df["BB_Upper"] - df["BB_Lower"]) / df["BB_Mid"] * 100,
        np.nan,
    )

    # Position within bands (0 = at lower, 1 = at upper)
    band_range = df["BB_Upper"] - df["BB_Lower"]
    df["BB_Pct"] = np.where(
        band_range != 0,
        (df["Close"] - df["BB_Lower"]) / band_range,
        0.5,  # When bands converge, price is at midpoint
    )

    return df
