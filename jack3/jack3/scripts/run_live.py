"""
Jack v3 -- Live trading entry point.

Usage:
  python scripts/run_live.py          # Paper mode (default, safe)
  python scripts/run_live.py --paper  # Paper mode (explicit)
  python scripts/run_live.py --live   # REAL MONEY -- be careful

The system runs from 08:45 to 15:35 IST.
Set environment variables before running:
  export DHAN_CLIENT_ID=your_id
  export DHAN_ACCESS_TOKEN=your_token
  export ANTHROPIC_API_KEY=your_key  (if using Anthropic provider)
"""
import argparse
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(description="Jack v3 -- BankNifty AI Trader")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--paper", action="store_true", default=True,
                            help="Run in paper trading mode (default, safe)")
    mode_group.add_argument("--live", action="store_true", default=False,
                            help="Run with REAL MONEY -- requires Dhan credentials")
    parser.add_argument("--config", default="config/settings.yaml",
                        help="Path to settings.yaml")
    args = parser.parse_args()

    live_mode = args.live and not args.paper

    if live_mode:
        print("\n" + "!" * 60)
        print("  WARNING: LIVE TRADING MODE -- REAL MONEY AT RISK")
        print("!" * 60)
        confirm = input("\nType 'YES I UNDERSTAND' to proceed: ")
        if confirm.strip() != "YES I UNDERSTAND":
            print("Aborted.")
            sys.exit(0)

    from engine.loop import JackMainLoop

    loop = JackMainLoop(config_path=args.config, live=live_mode)
    result = loop.run_full_day()

    print(f"\n[run_live] Day complete. Total P&L: Rs.{result.get('daily_pnl', 0):,.0f}")
    print(f"[run_live] Trades: {len(result.get('trades', []))}")


if __name__ == "__main__":
    main()
