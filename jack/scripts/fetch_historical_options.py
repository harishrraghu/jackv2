"""
Fetch 5 years of historical BANKNIFTY options data from Dhan's expired_options_data API.

For each 28-day window, for ATM-10 to ATM+10 strikes, for both WEEK and MONTH expiries,
this script fetches 15-minute OHLC, IV, OI, and spot for both CE and PE in one call.

Data is stored as daily parquet files in data/options/YYYY-MM-DD.parquet
Each file has columns:
    timestamp, expiry_type, rel_strike, abs_strike, option_type,
    open, high, low, close, iv, volume, oi, spot

Usage:
    python scripts/fetch_historical_options.py
    python scripts/fetch_historical_options.py --years 5 --interval 15
    python scripts/fetch_historical_options.py --from-date 2021-01-01 --to-date 2021-12-31
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

JACK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, JACK_ROOT)

from data.dhan_client import DhanClient, NSE_FNO

logger = logging.getLogger(__name__)

OPTIONS_DIR = os.path.join(JACK_ROOT, "data", "options")

# All relative strikes for BANKNIFTY (ATM +-10 allowed for index options)
STRIKES = (
    ["ATM"]
    + [f"ATM+{i}" for i in range(1, 11)]
    + [f"ATM-{i}" for i in range(1, 11)]
)

REQUIRED_FIELDS = ["open", "high", "low", "close", "iv", "volume", "strike", "oi", "spot"]


def date_windows(from_date: datetime, to_date: datetime, window_days: int = 28):
    """Generate (start, end) pairs of <=window_days each."""
    cur = from_date
    while cur < to_date:
        end = min(cur + timedelta(days=window_days - 1), to_date)
        yield cur, end
        cur = end + timedelta(days=1)


def parse_response(resp: dict, expiry_type: str, rel_strike: str,
                   option_type: str) -> pd.DataFrame:
    """
    Parse raw Dhan expired_options_data response.

    The API returns data nested under resp['data']['data']['ce'] (when drv_option_type='CALL')
    or resp['data']['data']['pe'] (when drv_option_type='PUT').
    Timestamps are Unix epoch integers in seconds.
    """
    if not resp or resp.get("status") != "success":
        return pd.DataFrame()

    try:
        inner = resp["data"]["data"]
    except (KeyError, TypeError):
        return pd.DataFrame()

    # 'ce' key populated for CALL requests, 'pe' for PUT requests
    side_key = "ce" if option_type == "CE" else "pe"
    side = inner.get(side_key, {})
    if not side:
        return pd.DataFrame()

    timestamps = side.get("timestamp", [])
    if not timestamps:
        return pd.DataFrame()

    n = len(timestamps)
    rows = []
    for i in range(n):
        rows.append({
            "timestamp": timestamps[i],          # Unix seconds int — converted below
            "expiry_type": expiry_type,
            "rel_strike": rel_strike,
            "option_type": option_type,
            "abs_strike": _safe_get(side.get("strike", []), i),
            "open": _safe_get(side.get("open", []), i),
            "high": _safe_get(side.get("high", []), i),
            "low": _safe_get(side.get("low", []), i),
            "close": _safe_get(side.get("close", []), i),
            "iv": _safe_get(side.get("iv", []), i),
            "volume": _safe_get(side.get("volume", []), i),
            "oi": _safe_get(side.get("oi", []), i),
            "spot": _safe_get(side.get("spot", []), i),
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    # Timestamps are Unix epoch seconds; convert and shift to IST (+05:30)
    df["timestamp"] = (
        pd.to_datetime(df["timestamp"], unit="s", utc=True)
        .dt.tz_convert("Asia/Kolkata")
        .dt.tz_localize(None)      # strip tzinfo for storage
    )
    return df


def _safe_get(lst, idx):
    try:
        v = lst[idx]
        return float(v) if v is not None else None
    except (IndexError, TypeError, ValueError):
        return None


def fetch_window(client: DhanClient, from_dt: datetime, to_dt: datetime,
                 interval: int) -> pd.DataFrame:
    """
    Fetch all strikes x expiry types for one date window.
    One API call per (expiry_type, strike) — response includes both CE and PE.
    """
    from_str = from_dt.strftime("%Y-%m-%d")
    to_str = to_dt.strftime("%Y-%m-%d")

    security_id = 25  # BANKNIFTY underlying
    instrument_type = "OPTIDX"

    all_chunks = []

    # expiry_code=0 fails server validation (falsy in JSON); use expiry_code=1 (nearest expiry)
    for expiry_flag in ["WEEK", "MONTH"]:
        for rel_strike in STRIKES:
            for drv_type, opt_label in [("CALL", "CE"), ("PUT", "PE")]:
                resp = client.get_expired_option_data(
                    security_id=security_id,
                    exchange_segment=NSE_FNO,
                    instrument_type=instrument_type,
                    expiry_flag=expiry_flag,
                    expiry_code=1,          # 1 = nearest expiry (0 is rejected as falsy)
                    strike=rel_strike,
                    drv_option_type=drv_type,
                    required_data=REQUIRED_FIELDS,
                    from_date=from_str,
                    to_date=to_str,
                    interval=interval,
                )

                chunk = parse_response(resp, expiry_flag, rel_strike, opt_label)
                if not chunk.empty:
                    all_chunks.append(chunk)

                # Rate-limit: ~5 req/s
                time.sleep(0.2)

    if not all_chunks:
        return pd.DataFrame()

    return pd.concat(all_chunks, ignore_index=True)


def save_by_day(window_df: pd.DataFrame, options_dir: str) -> int:
    """
    Split window DataFrame by calendar date and save/merge daily parquet files.
    Returns number of day files written.
    """
    if window_df.empty:
        return 0

    window_df = window_df.copy()
    window_df["date"] = window_df["timestamp"].dt.date
    days_written = 0

    for day, day_df in window_df.groupby("date"):
        day_str = str(day)
        path = os.path.join(options_dir, f"{day_str}.parquet")

        if os.path.exists(path):
            existing = pd.read_parquet(path)
            # Identify already-stored rows by composite key
            key_cols = ["timestamp", "expiry_type", "rel_strike", "option_type"]
            existing["_key"] = (
                existing["timestamp"].astype(str) + "|" +
                existing["expiry_type"] + "|" +
                existing["rel_strike"] + "|" +
                existing["option_type"]
            )
            day_df = day_df.copy()
            day_df["_key"] = (
                day_df["timestamp"].astype(str) + "|" +
                day_df["expiry_type"] + "|" +
                day_df["rel_strike"] + "|" +
                day_df["option_type"]
            )
            new_rows = day_df[~day_df["_key"].isin(existing["_key"])]
            if new_rows.empty:
                continue
            merged = pd.concat(
                [existing.drop(columns=["_key"]),
                 new_rows.drop(columns=["_key", "date"], errors="ignore")],
                ignore_index=True
            )
        else:
            merged = day_df.drop(columns=["date", "_key"], errors="ignore")

        merged = merged.drop(columns=["date", "_key"], errors="ignore")
        merged.to_parquet(path, index=False)
        days_written += 1

    return days_written


def main():
    parser = argparse.ArgumentParser(
        description="Fetch 5-year historical BANKNIFTY options data from Dhan"
    )
    parser.add_argument("--years", type=int, default=5,
                        help="Years of history to fetch (default: 5)")
    parser.add_argument("--interval", type=int, default=15,
                        choices=[1, 5, 15, 25, 60],
                        help="Candle interval in minutes (default: 15)")
    parser.add_argument("--from-date", type=str, default=None,
                        help="Override start date (YYYY-MM-DD)")
    parser.add_argument("--to-date", type=str, default=None,
                        help="Override end date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print plan without making API calls")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Skip confirmation prompt")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    client = DhanClient()
    if not client.is_configured():
        print("ERROR: Dhan credentials not configured. Edit jack/config/.env")
        sys.exit(1)

    to_dt = (datetime.strptime(args.to_date, "%Y-%m-%d")
             if args.to_date else datetime.now())
    from_dt = (datetime.strptime(args.from_date, "%Y-%m-%d")
               if args.from_date else to_dt - timedelta(days=365 * args.years))

    Path(OPTIONS_DIR).mkdir(parents=True, exist_ok=True)

    windows = list(date_windows(from_dt, to_dt, window_days=28))
    # One call per (strike x expiry_flag x option_type)
    calls_per_window = len(STRIKES) * 2 * 2   # strikes x WEEK/MONTH x CE/PE
    total_calls = len(windows) * calls_per_window

    print("Fetch plan:")
    print(f"  Date range   : {from_dt.date()} to {to_dt.date()}")
    print(f"  Windows      : {len(windows)} x 28-day chunks")
    print(f"  Strikes      : {len(STRIKES)} (ATM+-10)")
    print(f"  Interval     : {args.interval}m")
    print(f"  Est. API calls: ~{total_calls:,}")
    print(f"  Est. time    : ~{total_calls * 0.22 / 60:.0f} minutes at 5 req/s")
    print(f"  Output dir   : {OPTIONS_DIR}")
    print()

    if args.dry_run:
        print("DRY RUN - no API calls made.")
        return

    if not args.yes:
        confirm = input("Start fetching? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

    total_days_written = 0
    for idx, (w_from, w_to) in enumerate(windows, 1):
        print(f"[{idx}/{len(windows)}] {w_from.date()} to {w_to.date()}...", end=" ", flush=True)

        try:
            window_df = fetch_window(client, w_from, w_to, args.interval)
            if window_df.empty:
                print("no data")
                continue

            days_written = save_by_day(window_df, OPTIONS_DIR)
            total_days_written += days_written
            print(f"{len(window_df):,} rows to {days_written} day files")
        except KeyboardInterrupt:
            print("\nInterrupted by user.")
            break
        except Exception as e:
            logger.error(f"Window {w_from.date()} failed: {e}")
            print(f"ERROR: {e}")
            time.sleep(2)

    print(f"\nDone. Total day files written: {total_days_written}")
    print(f"Options data stored in: {OPTIONS_DIR}")


if __name__ == "__main__":
    main()
