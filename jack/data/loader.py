"""Data loader for Bank Nifty backtesting engine."""

from __future__ import annotations

import os
from typing import Iterator

import pandas as pd

TIMEFRAMES = ["1d", "2h", "1h", "15m", "5m", "1m"]
INTRADAY_TIMEFRAMES = TIMEFRAMES[1:]  # all except "1d"
FILE_PATTERN = "bank-nifty-{timeframe}-data.csv"
OHLC_COLS = ["Open", "High", "Low", "Close"]

_EMPTY_DF = pd.DataFrame()


def _clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Apply standard cleaning and derived columns to a raw OHLC DataFrame."""
    for col in OHLC_COLS:
        df[col] = df[col].astype("float64")
    df = df[df["High"] != df["Low"]]
    df = df.dropna(subset=OHLC_COLS)
    df["Range"] = df["High"] - df["Low"]
    df["Body"] = (df["Close"] - df["Open"]).abs()
    df["Return_pct"] = (df["Close"] - df["Open"]) / df["Open"] * 100
    df["Bullish"] = df["Close"] > df["Open"]
    return df.sort_values(["Date", "Time"]).reset_index(drop=True)


def load_timeframe(timeframe: str, base_path: str) -> pd.DataFrame:
    """Load and clean a single timeframe CSV."""
    file_path = os.path.join(base_path, FILE_PATTERN.format(timeframe=timeframe))
    df = pd.read_csv(file_path, dtype={"Time": str}, parse_dates=["Date"], dayfirst=True)
    return _clean_dataframe(df)


def load_all_timeframes(base_path: str) -> dict[str, pd.DataFrame]:
    """Load all timeframes and print a summary for each."""
    result: dict[str, pd.DataFrame] = {}
    for tf in TIMEFRAMES:
        df = load_timeframe(tf, base_path)
        print(f"{tf}: {len(df):,} rows | {df['Date'].min().date()} \u2192 {df['Date'].max().date()}")
        result[tf] = df
    return result


def get_daily_iterator(
    data: dict[str, pd.DataFrame],
    start_date: str,
    end_date: str,
) -> Iterator[dict]:
    """Yield one trading day at a time across all timeframes.

    Yields dicts with keys: date, daily, 2h, 1h, 15m, 5m, 1m.
    Days are driven by the 1d DataFrame. If intraday data is missing
    for a day, an empty DataFrame is yielded for that timeframe.
    """
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)

    daily_df = data["1d"]
    dates = sorted(daily_df[(daily_df["Date"] >= start) & (daily_df["Date"] <= end)]["Date"].unique())

    # Pre-resolve intraday frames once (empty sentinel if key absent or empty)
    intraday = {tf: data.get(tf, _EMPTY_DF) for tf in INTRADAY_TIMEFRAMES}

    for date in dates:
        ts = pd.Timestamp(date)
        day_data: dict = {
            "date": ts,
            "daily": daily_df[daily_df["Date"] == ts].copy(),
        }
        for tf, df in intraday.items():
            day_data[tf] = df[df["Date"] == ts].copy() if not df.empty else _EMPTY_DF
        yield day_data


def get_lookback(
    data: dict[str, pd.DataFrame],
    current_date: pd.Timestamp,
    n_days: int,
) -> dict[str, pd.DataFrame]:
    """Return last n_days of data strictly before current_date for each timeframe."""
    result: dict[str, pd.DataFrame] = {}
    for tf, df in data.items():
        past = df[df["Date"] < current_date]
        cutoff_dates = set(pd.Series(past["Date"].unique()).nlargest(n_days))
        result[tf] = past[past["Date"].isin(cutoff_dates)].copy()
    return result
