"""
Average Directional Index (ADX) indicator.

Measures trend strength regardless of direction.
ADX > 25 = trending market, ADX < 20 = ranging market.
Uses Wilder's smoothing throughout.
"""

import pandas as pd
import numpy as np

METADATA = {
    "name": "adx",
    "display_name": "Average Directional Index",
    "params": {"period": 14},
    "output_columns": ["ADX", "PDI", "MDI"],
    "timeframes": ["1d", "2h", "1h", "15m", "5m"],
}


def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """
    Compute ADX, +DI (PDI), and -DI (MDI) using Wilder's smoothing.

    +DI = smoothed +DM / ATR * 100
    -DI = smoothed -DM / ATR * 100
    DX = |PDI - MDI| / (PDI + MDI) * 100
    ADX = smoothed DX over period

    Args:
        df: DataFrame with OHLC data.
        period: ADX period (default: 14).

    Returns:
        Copy of DataFrame with ADX, PDI, MDI columns.
    """
    df = df.copy()
    period = params.get("period", METADATA["params"]["period"])

    if len(df) < period * 2:
        df["ADX"] = np.nan
        df["PDI"] = np.nan
        df["MDI"] = np.nan
        return df

    high = df["High"].values
    low = df["Low"].values
    close = df["Close"].values
    n = len(df)

    # True Range
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )

    # Directional Movement
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]

        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move

    # Wilder's smoothing
    alpha = 1.0 / period

    smoothed_tr = np.zeros(n)
    smoothed_plus_dm = np.zeros(n)
    smoothed_minus_dm = np.zeros(n)

    # Initialize with sum of first 'period' values
    smoothed_tr[period] = np.sum(tr[1:period + 1])
    smoothed_plus_dm[period] = np.sum(plus_dm[1:period + 1])
    smoothed_minus_dm[period] = np.sum(minus_dm[1:period + 1])

    for i in range(period + 1, n):
        smoothed_tr[i] = smoothed_tr[i - 1] - (smoothed_tr[i - 1] / period) + tr[i]
        smoothed_plus_dm[i] = smoothed_plus_dm[i - 1] - (smoothed_plus_dm[i - 1] / period) + plus_dm[i]
        smoothed_minus_dm[i] = smoothed_minus_dm[i - 1] - (smoothed_minus_dm[i - 1] / period) + minus_dm[i]

    # +DI and -DI
    pdi = np.full(n, np.nan)
    mdi = np.full(n, np.nan)
    dx = np.full(n, np.nan)

    for i in range(period, n):
        if smoothed_tr[i] != 0:
            pdi[i] = (smoothed_plus_dm[i] / smoothed_tr[i]) * 100
            mdi[i] = (smoothed_minus_dm[i] / smoothed_tr[i]) * 100
        else:
            pdi[i] = 0
            mdi[i] = 0

        denom = pdi[i] + mdi[i]
        if denom != 0:
            dx[i] = abs(pdi[i] - mdi[i]) / denom * 100
        else:
            dx[i] = 0

    # ADX = Wilder's smoothed DX
    adx = np.full(n, np.nan)
    # First ADX is average of first 'period' DX values
    first_adx_idx = period * 2
    if first_adx_idx < n:
        dx_for_avg = [d for d in dx[period:first_adx_idx] if not np.isnan(d)]
        if len(dx_for_avg) > 0:
            adx[first_adx_idx] = np.mean(dx_for_avg)

        for i in range(first_adx_idx + 1, n):
            if not np.isnan(adx[i - 1]) and not np.isnan(dx[i]):
                adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    df["ADX"] = adx
    df["PDI"] = pdi
    df["MDI"] = mdi

    return df
