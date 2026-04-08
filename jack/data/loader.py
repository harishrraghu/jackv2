"""Data loader for Bank Nifty CSV files."""

from __future__ import annotations

import os
from typing import Iterator

import pandas as pd

TIMEFRAMES = ["1d", "2h", "1h", "15m", "5m", "1m"]
FILE_PATTERN = "bank-nifty-{timeframe}-data.csv"


def load_timeframe(timeframe: str, base_path: str) -> pd.DataFrame:
    """Load a single timeframe CSV and return a cleaned DataFrame."""
    path = os.path.join(base_path, FILE_PATTERN.format(timeframe=timeframe))
    df = pd.read_csv(path, dayfirst=True, parse_dates=["Date"])

    if "Time" in df.columns:
        df["Time"] = df["Time"].astype(str)

    for col in ["Open", "High", "Low", "Close"]:
        if col in df.columns:
            df[col] = df[col].astype("float64")

    # High == Low indicates a bad/zero-range candle; drop it
    df = df[df["High"] != df["Low"]]
    df = df.dropna()

    df["Range"] = df["High"] - df["Low"]
    df["Body"] = abs(df["Close"] - df["Open"])
    df["Return_pct"] = (df["Close"] - df["Open"]) / df["Open"] * 100
    df["Bullish"] = df["Close"] > df["Open"]

    sort_cols = ["Date"] + (["Time"] if "Time" in df.columns else [])
    df = df.sort_values(sort_cols).reset_index(drop=True)

    return df


def load_all_timeframes(base_path: str) -> dict[str, pd.DataFrame]:
    """Load all six timeframes and return a dict keyed by timeframe string."""
    result: dict[str, pd.DataFrame] = {}
    for tf in TIMEFRAMES:
        try:
            df = load_timeframe(tf, base_path)
            result[tf] = df
            print(f"  [{tf}] loaded {len(df):,} rows  ({df['Date'].min().date()} → {df['Date'].max().date()})")
        except FileNotFoundError:
            print(f"  [{tf}] file not found — skipping")
    return result


def get_daily_iterator(data: pd.DataFrame, start_date: str, end_date: str) -> Iterator[dict]:
    """Yield one dict per trading day within [start_date, end_date]."""
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    mask = (data["Date"] >= start) & (data["Date"] <= end)
    subset = data[mask]
    for date, group in subset.groupby("Date"):
        yield {"date": date, "data": group.reset_index(drop=True)}


def get_lookback(data: pd.DataFrame, current_date: str, n_days: int) -> dict:
    """Return data for the n_days trading days strictly before current_date."""
    current = pd.Timestamp(current_date)
    past = data[data["Date"] < current]
    unique_dates = past["Date"].drop_duplicates().nlargest(n_days)
    subset = past[past["Date"].isin(unique_dates)].sort_values("Date").reset_index(drop=True)
    return {"data": subset, "n_days": n_days, "current_date": current}
