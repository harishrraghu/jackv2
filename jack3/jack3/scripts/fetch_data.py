"""
Jack v3 -- Historical Data Downloader.

One-time (or incremental) script to download BankNifty 5-minute candle
history directly from the Dhan v2 API and save to a local CSV file.

Dhan supports:
  - Up to 5 years of intraday history
  - 1, 5, 15, 25, 60-minute candles
  - Max 90 days per API call (this script handles chunking automatically)

Usage:
  # Download last 5 years (recommended first-time setup)
  python scripts/fetch_data.py --from 2020-01-01

  # Download a specific range
  python scripts/fetch_data.py --from 2022-01-01 --to 2022-12-31

  # Use 1-minute candles instead of 5-minute
  python scripts/fetch_data.py --from 2020-01-01 --interval 1

  # Resume an incomplete download (auto-detected)
  python scripts/fetch_data.py --from 2020-01-01

  # Save to a custom location
  python scripts/fetch_data.py --from 2020-01-01 --output /path/to/banknifty.csv

Credentials (set as environment variables before running):
  export DHAN_CLIENT_ID=your_client_id
  export DHAN_ACCESS_TOKEN=your_access_token

Or add them to a .env file and load with: python -c "import dotenv; dotenv.load_dotenv()"

After this completes, run the historical simulation:
  python scripts/run_historical_simulation.py --csv data/banknifty_5min.csv --from 2020-01-01
"""

import argparse
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(
        description="Download BankNifty historical candles from Dhan API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--from", dest="from_date",
        default=(date.today() - timedelta(days=365 * 5)).strftime("%Y-%m-%d"),
        help="Start date YYYY-MM-DD (default: 5 years ago)",
    )
    parser.add_argument(
        "--to", dest="to_date",
        default=date.today().strftime("%Y-%m-%d"),
        help="End date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--interval", type=int, default=5, choices=[1, 5, 15, 25, 60],
        help="Candle interval in minutes (default: 5)",
    )
    parser.add_argument(
        "--output", default="data/banknifty_5min.csv",
        help="Output CSV path (default: data/banknifty_5min.csv)",
    )
    parser.add_argument(
        "--security-id", default="25",
        help="Dhan security ID for BankNifty futures (default: 25)",
    )
    parser.add_argument(
        "--exchange", default="NSE_FNO",
        help="Exchange segment (default: NSE_FNO)",
    )
    parser.add_argument(
        "--instrument", default="FUTIDX",
        help="Instrument type (default: FUTIDX for index futures)",
    )
    parser.add_argument(
        "--no-resume", action="store_true",
        help="Start fresh even if output CSV already exists",
    )
    args = parser.parse_args()

    # Adjust output path for 1-min candles
    if args.interval == 1 and args.output == "data/banknifty_5min.csv":
        args.output = "data/banknifty_1min.csv"

    # Read credentials
    client_id = os.environ.get("DHAN_CLIENT_ID", "")
    access_token = os.environ.get("DHAN_ACCESS_TOKEN", "")

    if not client_id or not access_token:
        print("\nERROR: Dhan credentials not set.")
        print("Set environment variables before running:")
        print("  export DHAN_CLIENT_ID=your_client_id")
        print("  export DHAN_ACCESS_TOKEN=your_access_token")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  JACK v3 -- BankNifty Historical Data Downloader")
    print(f"{'='*60}")
    print(f"  Range:    {args.from_date} -> {args.to_date}")
    print(f"  Interval: {args.interval}-minute candles")
    print(f"  Output:   {args.output}")
    print(f"  Resume:   {'No (fresh start)' if args.no_resume else 'Yes (append missing)'}")
    print()

    from data.dhan_fetcher import DhanFetcher

    fetcher = DhanFetcher(client_id=client_id, access_token=access_token)

    df = fetcher.fetch_and_save(
        from_date=args.from_date,
        to_date=args.to_date,
        output_csv=args.output,
        security_id=args.security_id,
        interval=args.interval,
        exchange_segment=args.exchange,
        instrument_type=args.instrument,
        resume=not args.no_resume,
    )

    if df is not None and len(df) > 0:
        trading_days = df["datetime"].dt.date.nunique()
        date_range = f"{df['datetime'].min().date()} to {df['datetime'].max().date()}"
        print(f"\n{'='*60}")
        print(f"  Download complete!")
        print(f"  Total candles:   {len(df):,}")
        print(f"  Trading days:    {trading_days}")
        print(f"  Date range:      {date_range}")
        print(f"  File:            {args.output}")
        print(f"\n  Next step -- run historical simulation:")
        print(f"  python scripts/run_historical_simulation.py \\")
        print(f"    --csv {args.output} \\")
        print(f"    --from {args.from_date} --no-ai")
        print(f"{'='*60}\n")
    else:
        print("\nDownload failed or no data returned. Check credentials and date range.")
        sys.exit(1)


if __name__ == "__main__":
    main()
