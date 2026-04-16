"""
Jack v3 -- Strategy backtesting entry point.

Usage:
  python scripts/run_backtest.py --strategy first_hour_verdict
  python scripts/run_backtest.py --strategy first_hour_verdict --days 30
  python scripts/run_backtest.py --all --days 20
  python scripts/run_backtest.py --all --csv path/to/data.csv

Examples:
  python scripts/run_backtest.py --strategy gap_fill --days 20
  python scripts/run_backtest.py --all
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


ALL_STRATEGIES = [
    "first_hour_verdict",
    "gap_fill",
    "gap_up_fade",
    "streak_fade",
    "bb_squeeze",
    "vwap_reversion",
    "afternoon_breakout",
]


def main():
    parser = argparse.ArgumentParser(description="Jack v3 -- Strategy Backtester")
    parser.add_argument("--strategy", help="Strategy name to backtest")
    parser.add_argument("--all", action="store_true", help="Backtest all strategies")
    parser.add_argument("--days", type=int, default=20, help="Lookback days (default: 20)")
    parser.add_argument("--csv", help="Path to CSV file with intraday candle data")
    parser.add_argument("--config", default="config/settings.yaml", help="Config path")
    args = parser.parse_args()

    if not args.strategy and not args.all:
        parser.print_help()
        sys.exit(1)

    import yaml
    with open(args.config) as f:
        config = yaml.safe_load(f)

    config["lab"]["backtest_lookback_days"] = args.days

    # Load data
    if args.csv:
        import pandas as pd
        print(f"[Backtest] Loading data from CSV: {args.csv}")
        candle_data = pd.read_csv(args.csv, parse_dates=True)
        daily_data = pd.DataFrame()
    else:
        print(f"[Backtest] Fetching {args.days} days of data from Dhan...")
        from data.dhan_client import create_dhan_client
        client = create_dhan_client(config)
        security_id = config["dhan"]["banknifty_index_id"]
        candle_data = client.get_historical_intraday(security_id=security_id, interval=5, days_back=args.days + 5)
        daily_data = client.get_historical_daily(security_id=security_id, days=args.days + 30)

    strategies_to_test = ALL_STRATEGIES if args.all else [args.strategy]

    print(f"\n{'='*60}")
    print(f"  JACK v3 BACKTEST -- {args.days} days")
    print(f"{'='*60}\n")

    results = []
    for strategy_name in strategies_to_test:
        print(f"Testing: {strategy_name}")
        from lab.backtester import backtest_strategy
        result = backtest_strategy(
            strategy_name=strategy_name,
            candle_data=candle_data,
            daily_data=daily_data,
            config=config,
        )
        results.append(result)
        _print_result(result)

    if args.all and len(results) > 1:
        _print_summary_table(results)


def _print_result(result: dict) -> None:
    """Print a single strategy backtest result."""
    if result.get("error"):
        print(f"  ERROR: {result['error']}\n")
        return
    print(f"  Win Rate:    {result['win_rate']:.1f}%")
    print(f"  Trades:      {result['total_trades']}")
    print(f"  Avg P&L:     Rs.{result['avg_pnl']:,.0f}")
    print(f"  Total P&L:   Rs.{result['total_pnl']:,.0f}")
    print(f"  Max DD:      {result['max_drawdown_pct']:.2f}%")
    print(f"  Sharpe:      {result['sharpe']:.3f}")
    print()


def _print_summary_table(results: list) -> None:
    """Print a comparison table of all strategy results."""
    print(f"\n{'='*80}")
    print(f"  COMPARISON TABLE")
    print(f"{'='*80}")
    print(f"{'Strategy':<25} {'Win%':>7} {'Trades':>7} {'AvgPnL':>10} {'Sharpe':>8} {'MaxDD%':>8}")
    print("-" * 80)

    # Sort by win_rate * sqrt(trades) score
    import math
    scored = [(r, r.get("win_rate", 0) * math.sqrt(r.get("total_trades", 0))) for r in results]
    scored.sort(key=lambda x: x[1], reverse=True)

    for result, score in scored:
        if not result.get("error"):
            print(
                f"{result['strategy']:<25} "
                f"{result['win_rate']:>6.1f}% "
                f"{result['total_trades']:>7} "
                f"Rs.{result['avg_pnl']:>9,.0f} "
                f"{result['sharpe']:>8.3f} "
                f"{result['max_drawdown_pct']:>7.2f}%"
            )
    print()


if __name__ == "__main__":
    main()
