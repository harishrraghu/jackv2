"""
Hurst Exponent (Simplified) indicator.

Uses the Rescaled Range (R/S) method to estimate the Hurst exponent.
H > 0.5 = trending/persistent, H < 0.5 = mean-reverting, H ≈ 0.5 = random walk.

Computationally expensive — only computed every 5 rows and forward-filled.
"""

import pandas as pd
import numpy as np

METADATA = {
    "name": "hurst",
    "display_name": "Hurst Exponent (R/S Method)",
    "params": {"max_lag": 20},
    "output_columns": ["Hurst"],
    "timeframes": ["1d"],
}


def _compute_hurst_rs(series: np.ndarray) -> float:
    """
    Compute Hurst exponent using R/S analysis on a price series.

    Args:
        series: Array of prices (at least 20 values).

    Returns:
        Hurst exponent estimate. Returns NaN if computation fails.
    """
    if len(series) < 20:
        return np.nan

    # Use log returns for stationarity
    returns = np.diff(np.log(series))
    n = len(returns)

    if n < 10:
        return np.nan

    # Compute R/S for different sub-series lengths
    lags = []
    rs_values = []

    for lag in range(10, min(n, 100), 5):
        rs_list = []
        # Split into sub-series of length 'lag'
        for start in range(0, n - lag + 1, lag):
            sub = returns[start:start + lag]
            if len(sub) < lag:
                continue

            mean_sub = np.mean(sub)
            cumdev = np.cumsum(sub - mean_sub)
            r = np.max(cumdev) - np.min(cumdev)
            s = np.std(sub, ddof=1)

            if s > 0:
                rs_list.append(r / s)

        if len(rs_list) > 0:
            lags.append(lag)
            rs_values.append(np.mean(rs_list))

    if len(lags) < 2:
        return np.nan

    # Log-log regression to find slope (Hurst exponent)
    log_lags = np.log(lags)
    log_rs = np.log(rs_values)

    try:
        # Simple linear regression
        n_pts = len(log_lags)
        sum_x = np.sum(log_lags)
        sum_y = np.sum(log_rs)
        sum_xy = np.sum(log_lags * log_rs)
        sum_x2 = np.sum(log_lags ** 2)

        denom = n_pts * sum_x2 - sum_x ** 2
        if denom == 0:
            return np.nan

        hurst = (n_pts * sum_xy - sum_x * sum_y) / denom
        return max(0.0, min(1.0, hurst))  # Clamp to [0, 1]

    except Exception:
        return np.nan


def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """
    Compute Hurst exponent using R/S method.

    Only computed every 5 rows and forward-filled to reduce computation.
    Requires max_lag * 5 data points of lookback.

    Args:
        df: DataFrame with daily OHLC data.
        max_lag: Maximum lag for R/S computation (default: 20).

    Returns:
        Copy of DataFrame with Hurst column.
    """
    df = df.copy()
    max_lag = params.get("max_lag", METADATA["params"]["max_lag"])

    lookback = max_lag * 5

    if len(df) < lookback:
        df["Hurst"] = np.nan
        return df

    hurst_values = np.full(len(df), np.nan)
    close = df["Close"].values

    for i in range(lookback, len(df), 5):  # Every 5 rows
        window = close[max(0, i - lookback):i + 1]
        hurst_values[i] = _compute_hurst_rs(window)

    df["Hurst"] = hurst_values
    # Forward-fill the gaps
    df["Hurst"] = df["Hurst"].ffill()

    return df
