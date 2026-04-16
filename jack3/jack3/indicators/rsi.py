"""
Relative Strength Index (RSI) indicator.

Uses Wilder's smoothing method (exponential moving average with alpha=1/period)
to compute the ratio of average gains to average losses, scaled to 0–100.
"""

import pandas as pd
import numpy as np

METADATA = {
    "name": "rsi",
    "display_name": "Relative Strength Index",
    "params": {"period": 14},
    "output_columns": ["RSI"],
    "timeframes": ["1d", "2h", "1h", "15m", "5m"],
}


def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """
    Compute RSI using Wilder's smoothing.

    Args:
        df: DataFrame with OHLC data.
        period: RSI period (default: 14).

    Returns:
        Copy of DataFrame with RSI column (0–100 scale).
    """
    df = df.copy()
    period = params.get("period", METADATA["params"]["period"])

    if len(df) < period + 1:
        df["RSI"] = np.nan
        return df

    # Price changes
    delta = df["Close"].diff()

    gains = delta.clip(lower=0)
    losses = (-delta).clip(lower=0)

    # Wilder's smoothing: EMA with alpha = 1/period
    avg_gain = gains.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    # Avoid division by zero
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))

    # Fill NaN RSI where avg_loss is 0 (all gains → RSI = 100)
    df.loc[avg_loss == 0, "RSI"] = 100.0

    return df
