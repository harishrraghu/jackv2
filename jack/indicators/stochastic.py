"""
Stochastic Oscillator indicator.

%K measures where the close falls relative to the high-low range over a period.
%D is a smoothed (SMA) version of %K for signal confirmation.
"""

import pandas as pd
import numpy as np

METADATA = {
    "name": "stochastic",
    "display_name": "Stochastic Oscillator",
    "params": {"k_period": 14, "d_period": 3},
    "output_columns": ["Stoch_K", "Stoch_D"],
    "timeframes": ["1d", "2h", "1h", "15m", "5m"],
}


def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """
    Compute Stochastic %K and %D.

    %K = (Close - Lowest Low) / (Highest High - Lowest Low) * 100
    %D = SMA(d_period) of %K

    Args:
        df: DataFrame with OHLC data.
        k_period: Lookback period for %K (default: 14).
        d_period: Smoothing period for %D (default: 3).

    Returns:
        Copy of DataFrame with Stoch_K and Stoch_D columns.
    """
    df = df.copy()
    k_period = params.get("k_period", METADATA["params"]["k_period"])
    d_period = params.get("d_period", METADATA["params"]["d_period"])

    if len(df) < k_period:
        df["Stoch_K"] = np.nan
        df["Stoch_D"] = np.nan
        return df

    lowest_low = df["Low"].rolling(window=k_period).min()
    highest_high = df["High"].rolling(window=k_period).max()

    hl_range = highest_high - lowest_low
    # Avoid division by zero when range is 0
    df["Stoch_K"] = np.where(
        hl_range == 0,
        50.0,  # When range is 0, price is in the middle
        (df["Close"] - lowest_low) / hl_range * 100,
    )

    df["Stoch_D"] = df["Stoch_K"].rolling(window=d_period).mean()

    return df
