"""
Fetch historical BankNifty data from Dhan API and save as CSV.

Dhan historical_daily_data gives daily OHLCV going back years.
Dhan intraday_minute_data only gives last 5 trading days.

For backtesting, CSVs in data/raw/ remain the primary source.
This script supplements with recent daily data from Dhan.

Usage:
    python scripts/fetch_dhan_history.py
    python scripts/fetch_dhan_history.py --years 5
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta

import pandas as pd

# Add project root to path
JACK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, JACK_ROOT)

from data.dhan_client import DhanClient, IDX

logger = logging.getLogger(__name__)
DATA_DIR = os.path.join(JACK_ROOT, "data", "raw")


def fetch_daily_history(client: DhanClient, years: int = 5) -> pd.DataFrame:
    """Fetch daily OHLCV for BankNifty index from Dhan.

    Dhan limits historical_daily_data to ~2000 days per call,
    so we chunk into 1-year windows.
    """
    security_id = client.get_security_id("BANKNIFTY", "index")
    end_date = datetime.now()
    all_rows = []

    for y in range(years):
        to_dt = end_date - timedelta(days=365 * y)
        from_dt = to_dt - timedelta(days=365)
        from_str = from_dt.strftime("%Y-%m-%d")
        to_str = to_dt.strftime("%Y-%m-%d")

        logger.info(f"Fetching {from_str} to {to_str}...")
        resp = client.get_historical_daily(
            security_id=security_id,
            exchange_segment=IDX,
            instrument_type="INDEX",
            from_date=from_str,
            to_date=to_str,
        )

        if resp and resp.get("status") == "success":
            data = resp.get("data", {})
            if "candles" in data:
                # Format 1: List of lists
                candles = data.get("candles", [])
                if candles:
                    logger.info(f"  Got {len(candles)} candles")
                    all_rows.extend(candles)
                else:
                    logger.warning(f"  No candle data for {from_str} to {to_str}")
            elif "open" in data and "timestamp" in data:
                # Format 2: Dict of lists (what we saw in tests)
                count = len(data["timestamp"])
                logger.info(f"  Got {count} candles (dict format)")
                for i in range(count):
                    all_rows.append([
                        data["timestamp"][i],
                        data["open"][i],
                        data["high"][i],
                        data["low"][i],
                        data["close"][i],
                        data["volume"][i]
                    ])
            else:
                logger.warning(f"  No candle data for {from_str} to {to_str}")
        else:
            logger.warning(f"  API error for {from_str} to {to_str}: {resp}")

    if not all_rows:
        logger.error("No data fetched from Dhan")
        return pd.DataFrame()

    # Dhan candles format: [timestamp, open, high, low, close, volume]
    df = pd.DataFrame(all_rows, columns=["timestamp", "Open", "High", "Low", "Close", "Volume"])
    df["Date"] = pd.to_datetime(df["timestamp"])
    df["Instrument"] = "BANKNIFTY"
    df["Time"] = ""
    df = df.drop(columns=["timestamp"])
    df = df.drop_duplicates(subset=["Date"]).sort_values("Date").reset_index(drop=True)

    return df[["Instrument", "Date", "Time", "Open", "High", "Low", "Close", "Volume"]]


def merge_with_existing(new_df: pd.DataFrame, csv_path: str) -> pd.DataFrame:
    """Merge new Dhan data with existing CSV, preferring existing data."""
    if not os.path.exists(csv_path):
        return new_df

    existing = pd.read_csv(csv_path)
    existing["Date"] = pd.to_datetime(existing["Date"], dayfirst=True, errors="coerce")

    # Find dates not in existing
    existing_dates = set(existing["Date"].dt.date)
    new_only = new_df[~new_df["Date"].dt.date.isin(existing_dates)]

    if new_only.empty:
        logger.info("No new dates to add")
        return existing

    logger.info(f"Adding {len(new_only)} new dates from Dhan")
    merged = pd.concat([existing, new_only], ignore_index=True)
    merged = merged.sort_values("Date").reset_index(drop=True)
    return merged


def fetch_intraday_recent(client: DhanClient) -> pd.DataFrame:
    """Fetch last 5 days of intraday 15m data from Dhan."""
    security_id = client.get_security_id("BANKNIFTY", "index")
    end_date = datetime.now()
    start_date = end_date - timedelta(days=7)

    resp = client.get_intraday_data(
        security_id=security_id,
        exchange_segment=IDX,
        instrument_type="INDEX",
        from_date=start_date.strftime("%Y-%m-%d"),
        to_date=end_date.strftime("%Y-%m-%d"),
        interval=15,
    )

    if not resp or resp.get("status") != "success":
        logger.warning(f"Intraday fetch failed: {resp}")
        return pd.DataFrame()

    data = resp.get("data", {})
    all_rows = []
    if "candles" in data:
        all_rows = data.get("candles", [])
    elif "open" in data and "timestamp" in data:
        count = len(data["timestamp"])
        for i in range(count):
            all_rows.append([
                data["timestamp"][i],
                data["open"][i],
                data["high"][i],
                data["low"][i],
                data["close"][i],
                data["volume"][i]
            ])

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows, columns=["timestamp", "Open", "High", "Low", "Close", "Volume"])
    df["datetime"] = pd.to_datetime(df["timestamp"])
    df["Date"] = df["datetime"].dt.date
    df["Time"] = df["datetime"].dt.strftime("%H:%M:%S")
    df["Instrument"] = "BANKNIFTY"
    df = df.drop(columns=["timestamp", "datetime"])

    return df[["Instrument", "Date", "Time", "Open", "High", "Low", "Close", "Volume"]]


def main():
    parser = argparse.ArgumentParser(description="Fetch BankNifty history from Dhan")
    parser.add_argument("--years", type=int, default=5, help="Years of daily data")
    parser.add_argument("--intraday", action="store_true", help="Also fetch recent intraday")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    client = DhanClient()
    if not client.is_configured():
        print("Dhan credentials not configured. Edit jack/config/.env")
        sys.exit(1)

    os.makedirs(DATA_DIR, exist_ok=True)

    # Daily data
    print(f"Fetching {args.years} years of daily BankNifty data from Dhan...")
    daily_df = fetch_daily_history(client, args.years)
    if not daily_df.empty:
        csv_path = os.path.join(DATA_DIR, "bank-nifty-1d-data.csv")
        merged = merge_with_existing(daily_df, csv_path)
        merged.to_csv(csv_path, index=False)
        print(f"Saved {len(merged)} daily rows to {csv_path}")

    # Intraday data
    if args.intraday:
        print("Fetching recent intraday 15m data from Dhan...")
        intraday_df = fetch_intraday_recent(client)
        if not intraday_df.empty:
            csv_path = os.path.join(DATA_DIR, "bank-nifty-15m-data.csv")
            merged = merge_with_existing(intraday_df, csv_path)
            merged.to_csv(csv_path, index=False)
            print(f"Saved {len(merged)} intraday rows to {csv_path}")


if __name__ == "__main__":
    main()
