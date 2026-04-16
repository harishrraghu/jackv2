"""
Average True Range (ATR) indicator.

True Range captures the full volatility of each bar including gaps.
ATR is the rolling mean of True Range. ATR_Pct normalizes ATR as a
percentage of price for cross-period comparisons.
"""

import pandas as pd
import numpy as np

METADATA = {
    "name": "atr",
    "display_name": "Average True Range",
    "params": {"period": 14},
    "output_columns": ["ATR", "ATR_Pct"],
    "timeframes": ["1d", "2h", "1h", "15m", "5m"],
}


def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """
    Compute ATR and ATR_Pct.

    True Range = max(H-L, |H-PrevClose|, |L-PrevClose|)
    ATR = rolling mean of TR over period
    ATR_Pct = ATR / Close * 100

    Args:
        df: DataFrame with OHLC data.
        period: ATR period (default: 14).

    Returns:
        Copy of DataFrame with ATR and ATR_Pct columns.
    """
    df = df.copy()
    period = params.get("period", METADATA["params"]["period"])

    if len(df) < 2:
        df["ATR"] = np.nan
        df["ATR_Pct"] = np.nan
        return df

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

    df["TR"] = tr

    if len(df) < period:
        df["ATR"] = np.nan
        df["ATR_Pct"] = np.nan
        df.drop(columns=["TR"], inplace=True)
        return df

    df["ATR"] = df["TR"].rolling(window=period).mean()
    df["ATR_Pct"] = df["ATR"] / df["Close"] * 100

    df.drop(columns=["TR"], inplace=True)

    return df
