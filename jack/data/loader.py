"""OHLC data loader for Bank Nifty backtesting engine."""

import os
from typing import Iterator

import pandas as pd

TIMEFRAMES = ["1d", "2h", "1h", "15m", "5m", "1m"]
FILE_PATTERN = "bank-nifty-{timeframe}-data.csv"


def load_timeframe(timeframe: str, base_path: str) -> pd.DataFrame:
    """Load a single timeframe CSV and return a cleaned, enriched DataFrame."""
    path = os.path.join(base_path, FILE_PATTERN.format(timeframe=timeframe))
    df = pd.read_csv(path, dayfirst=True)

    # Parse Date column
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True)

    # Keep Time as string if present, otherwise set empty string
    if "Time" not in df.columns:
        df["Time"] = ""
    else:
        df["Time"] = df["Time"].astype(str)

    # Convert OHLC to float64
    for col in ["Open", "High", "Low", "Close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")

    # Drop NaN rows and rows where High == Low
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df = df[df["High"] != df["Low"]]

    # Derived columns
    df["Range"] = df["High"] - df["Low"]
    df["Body"] = (df["Close"] - df["Open"]).abs()
    df["Return_pct"] = (df["Close"] - df["Open"]) / df["Open"] * 100
    df["Bullish"] = df["Close"] > df["Open"]

    # Sort by Date then Time
    df = df.sort_values(["Date", "Time"]).reset_index(drop=True)

    return df


def load_all_timeframes(base_path: str) -> dict:
    """Load all 6 timeframes and return a dict keyed by timeframe string."""
    data = {}
    for tf in TIMEFRAMES:
        try:
            df = load_timeframe(tf, base_path)
            data[tf] = df
            print(f"[loader] {tf}: {len(df)} rows loaded")
        except FileNotFoundError:
            print(f"[loader] {tf}: file not found, skipping")
            data[tf] = pd.DataFrame()
    return data


def get_daily_iterator(
    data: pd.DataFrame, start_date: str, end_date: str
) -> Iterator[dict]:
    """Yield one dict per trading day between start_date and end_date."""
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    mask = (data["Date"] >= start) & (data["Date"] <= end)
    filtered = data[mask]
    for date, group in filtered.groupby("Date"):
        yield {"date": date, "rows": group.reset_index(drop=True)}


def get_lookback(data: pd.DataFrame, current_date: str, n_days: int) -> dict:
    """Return last n_days of rows strictly before current_date."""
    current = pd.Timestamp(current_date)
    past = data[data["Date"] < current]
    unique_dates = past["Date"].unique()
    unique_dates = sorted(unique_dates)[-n_days:]
    subset = past[past["Date"].isin(unique_dates)]
    return {"dates": unique_dates, "rows": subset.reset_index(drop=True)}
