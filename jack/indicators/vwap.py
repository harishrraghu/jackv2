"""
Volume Weighted Average Price (VWAP) indicator.
Resets each day. Requires Volume column in the data.
If no volume data exists, uses a price-only proxy (typical price SMA).
"""

import pandas as pd
import numpy as np

METADATA = {
    "name": "vwap",
    "display_name": "Volume Weighted Average Price",
    "params": {},
    "output_columns": ["VWAP", "VWAP_Upper", "VWAP_Lower"],
    "timeframes": ["5m", "15m"],
}


def compute(df: pd.DataFrame, **params) -> pd.DataFrame:
    """
    Compute intraday VWAP with standard deviation bands.

    Resets at the start of each trading day.
    Falls back to typical price SMA if no Volume column.

    VWAP = cumulative(TP * Volume) / cumulative(Volume)
    TP = (High + Low + Close) / 3
    VWAP_Upper = VWAP + 1 stdev
    VWAP_Lower = VWAP - 1 stdev
    """
    df = df.copy()

    has_volume = "Volume" in df.columns and df["Volume"].sum() > 0

    # Typical price
    df["_TP"] = (df["High"] + df["Low"] + df["Close"]) / 3

    if has_volume:
        df["_TPxVol"] = df["_TP"] * df["Volume"]

        vwap_values = []
        upper_values = []
        lower_values = []

        for date in df["Date"].unique():
            mask = df["Date"] == date
            day_data = df[mask]

            cum_tpv = day_data["_TPxVol"].cumsum()
            cum_vol = day_data["Volume"].cumsum()

            vwap = cum_tpv / cum_vol.replace(0, np.nan)

            # Rolling std of TP for bands
            tp_values = day_data["_TP"].values
            stds = []
            for i in range(len(tp_values)):
                if i < 1:
                    stds.append(0)
                else:
                    stds.append(np.std(tp_values[:i+1], ddof=0))

            stds = np.array(stds)
            vwap_arr = vwap.values

            vwap_values.extend(vwap_arr.tolist())
            upper_values.extend((vwap_arr + stds).tolist())
            lower_values.extend((vwap_arr - stds).tolist())

        df["VWAP"] = vwap_values
        df["VWAP_Upper"] = upper_values
        df["VWAP_Lower"] = lower_values
    else:
        # Fallback: cumulative typical price average per day
        vwap_values = []
        for date in df["Date"].unique():
            mask = df["Date"] == date
            day_tp = df.loc[mask, "_TP"]
            vwap_values.extend(day_tp.expanding().mean().tolist())

        df["VWAP"] = vwap_values
        df["VWAP_Upper"] = df["VWAP"] * 1.003  # ~0.3% band proxy
        df["VWAP_Lower"] = df["VWAP"] * 0.997

    # Clean up temp columns
    df.drop(columns=[c for c in df.columns if c.startswith("_")], inplace=True)

    return df
