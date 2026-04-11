"""
Jack — Bank Nifty Backtesting Engine CLI.

Usage:
    python sim.py run --split train [--verbose]
    python sim.py analyze --split train
    python sim.py montecarlo --split train [--n 10000]
    python sim.py walkforward [--train-years 2] [--test-months 3]
    python sim.py benchmark --split train
    python sim.py report --split train --output report.html
    python sim.py validate-data
    python sim.py indicators
    python sim.py strategies
    python sim.py review [--days 5]
"""

import argparse
import json
import os
import sys
import pandas as pd

# Ensure the jack directory is in the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ANSI colors
class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def cmd_run(args):
    """Run simulation on specified split."""
    from engine.simulator import Simulator

    sim = Simulator(config_path=args.config)
    results = sim.run(split=args.split, verbose=args.verbose)

    print(f"\n{Colors.BOLD}{'='*60}")
    print(f"  SIMULATION COMPLETE — {args.split.upper()} SPLIT")
    print(f"{'='*60}{Colors.RESET}")
    print(f"  Period: {results.get('start_date')} -> {results.get('end_date')}")
    print(f"  Trading days: {results.get('total_days', 0)}")
    print(f"  Total trades: {results.get('total_trades', 0)}")

    wr = results.get('win_rate', 0)
    wr_color = Colors.GREEN if wr > 50 else Colors.RED
    print(f"  Win rate: {wr_color}{wr:.1f}%{Colors.RESET}")

    pnl = results.get('net_pnl', 0)
    pnl_color = Colors.GREEN if pnl > 0 else Colors.RED
    print(f"  Net P&L: {pnl_color}Rs. {pnl:,.2f}{Colors.RESET}")

    ret = results.get('return_pct', 0)
    ret_color = Colors.GREEN if ret > 0 else Colors.RED
    print(f"  Return: {ret_color}{ret:.2f}%{Colors.RESET}")

    print(f"  Max drawdown: {Colors.RED}{results.get('max_drawdown_pct', 0):.2f}%{Colors.RESET}")
    print(f"  Sharpe ratio: {results.get('sharpe_ratio', 0):.3f}")

    if results.get("by_strategy"):
        print(f"\n  {Colors.BOLD}By Strategy:{Colors.RESET}")
        for s, data in results["by_strategy"].items():
            p = data.get("pnl", 0)
            c = Colors.GREEN if p > 0 else Colors.RED
            print(f"    {s:25s}: {data.get('trades', 0):3d} trades | "
                  f"WR: {data.get('win_rate', 0):5.1f}% | "
                  f"P&L: {c}Rs. {p:+,.0f}{Colors.RESET}")

    # Save results
    results_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "journal", "logs", f"results_{args.split}.json")
    os.makedirs(os.path.dirname(results_path), exist_ok=True)
    safe_results = {k: v for k, v in results.items() if k != "equity_data"}  # Keep trade_log, exclude raw equity arrays if huge
    # Actually equity_curve is small enough too, just save everything except huge dataframes if any
    safe_results = {k: v for k, v in results.items() if not isinstance(v, pd.DataFrame)}
    with open(results_path, "w") as f:
        json.dump(safe_results, f, indent=2, default=str)


def cmd_analyze(args):
    """Run performance analysis on last simulation results."""
    from analysis.performance import PerformanceAnalyzer

    # Load trade log
    journal_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "journal", "logs")
    summary_path = os.path.join(journal_dir, f"results_{args.split}.json")

    if not os.path.exists(summary_path):
        print(f"{Colors.RED}No results found for {args.split} split. Run simulation first.{Colors.RESET}")
        return

    with open(summary_path, "r") as f:
        results = json.load(f)

    trade_log = results.get("trade_log", [])
    initial = results.get("initial_capital", 1000000)

    if not trade_log:
        print(f"{Colors.YELLOW}No trades to analyze.{Colors.RESET}")
        return

    analyzer = PerformanceAnalyzer(trade_log, initial)
    analyzer.print_report()


def cmd_montecarlo(args):
    """Run Monte Carlo validation."""
    from analysis.monte_carlo import MonteCarloValidator

    journal_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "journal", "logs")
    summary_path = os.path.join(journal_dir, f"results_{args.split}.json")

    if not os.path.exists(summary_path):
        print(f"{Colors.RED}No results found. Run simulation first.{Colors.RESET}")
        return

    with open(summary_path, "r") as f:
        results = json.load(f)

    trade_log = results.get("trade_log", [])
    initial = results.get("initial_capital", 1000000)

    mc = MonteCarloValidator(trade_log, initial, n_simulations=args.n)
    mc.print_report()


def cmd_walkforward(args):
    """Run walk-forward validation."""
    from analysis.walk_forward import WalkForwardValidator
    import yaml

    config_path = args.config
    if not os.path.isabs(config_path):
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), config_path)

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    wf = WalkForwardValidator(config, config_path)
    wf.print_report()


def cmd_benchmark(args):
    """Run benchmark comparison."""
    from analysis.performance import BenchmarkComparison
    from data.loader import load_all_timeframes
    import yaml

    config_path = args.config
    if not os.path.isabs(config_path):
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), config_path)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             config["data"]["base_path"])
    data = load_all_timeframes(data_path)
    daily = data.get("1d")

    journal_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "journal", "logs")
    results_path = os.path.join(journal_dir, f"results_{args.split}.json")

    equity_curve = []
    initial = config["trading"]["initial_capital"]
    if os.path.exists(results_path):
        with open(results_path) as f:
            results = json.load(f)
        equity_curve = results.get("equity_curve", [])

    bc = BenchmarkComparison(equity_curve, daily, initial)
    bc.print_comparison()


def cmd_report(args):
    """Generate full HTML report."""
    from engine.simulator import Simulator
    from analysis.performance import PerformanceAnalyzer
    from analysis.monte_carlo import MonteCarloValidator
    from analysis.report import ReportGenerator

    print(f"{Colors.BOLD}Running full report pipeline...{Colors.RESET}")

    # Run simulation
    print("\n1. Running simulation...")
    sim = Simulator(config_path=args.config)
    results = sim.run(split=args.split, verbose=False)

    # Analyze
    print("2. Computing analytics...")
    trade_log = results.get("trade_log", [])
    initial = results.get("initial_capital", 1000000)

    analytics = {}
    if trade_log:
        analyzer = PerformanceAnalyzer(trade_log, initial)
        analytics = analyzer.compute_all()
        results.update(analytics)

    # Monte Carlo
    print("3. Running Monte Carlo (10,000 simulations)...")
    mc_results = {}
    if len(trade_log) >= 5:
        mc = MonteCarloValidator(trade_log, initial)
        mc_results = mc.run_shuffle_test()

    # Generate report
    print("4. Generating HTML report...")
    report = ReportGenerator(results, monte_carlo=mc_results)
    output = args.output
    if not os.path.isabs(output):
        output = os.path.join(os.path.dirname(os.path.abspath(__file__)), output)
    report.generate(output)

    print(f"\n{Colors.GREEN}✓ Report saved to: {output}{Colors.RESET}")


def cmd_validate_data(args):
    """Run data validation."""
    from data.loader import load_all_timeframes
    from data.validator import validate_data
    import yaml

    config_path = args.config
    if not os.path.isabs(config_path):
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), config_path)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             config["data"]["base_path"])
    data = load_all_timeframes(data_path)
    validate_data(data)


def cmd_review(args):
    """Weekly journal review."""
    from analysis.journal_analyzer import JournalAnalyzer
    journal_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "journal", "logs")
    analyzer = JournalAnalyzer(journal_dir=journal_dir)
    print(f"{Colors.BOLD}Analyzing last {args.days} days...{Colors.RESET}\n")
    memo = analyzer.generate_weekly_memo(n_days=args.days)
    print(json.dumps(memo, indent=2))


def cmd_indicators(args):
    """List all registered indicators."""
    from indicators.registry import IndicatorRegistry

    reg = IndicatorRegistry(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "indicators")
    )

    indicators = sorted(reg.list_indicators(), key=lambda x: x["name"])
    print(f"\n{Colors.BOLD}Registered Indicators: {len(indicators)}{Colors.RESET}\n")

    for ind in indicators:
        cols = ", ".join(ind["output_columns"])
        tfs = ", ".join(ind["timeframes"])
        print(f"  {Colors.GREEN}{ind['name']:15s}{Colors.RESET} "
              f"| {ind['display_name']:30s} | columns: {cols}")


def cmd_strategies(args):
    """List all strategies with parameters."""
    from strategies.first_hour_verdict import FirstHourVerdict
    from strategies.gap_fill import GapFill
    from strategies.streak_fade import StreakFade
    from strategies.bb_squeeze import BBSqueezeBreakout
    from strategies.gap_up_fade import GapUpFade
    from strategies.vwap_reversion import VWAPReversion
    from strategies.afternoon_breakout import AfternoonBreakout

    strategies = [
        FirstHourVerdict(), GapFill(), StreakFade(),
        BBSqueezeBreakout(), GapUpFade(), VWAPReversion(),
        AfternoonBreakout(),
    ]

    print(f"\n{Colors.BOLD}Strategies: {len(strategies)}{Colors.RESET}\n")

    for s in strategies:
        tunable = [k for k, v in s.params.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
        print(f"  {Colors.GREEN}{s.name:25s}{Colors.RESET} "
              f"| params: {len(tunable)}/5 budget | "
              f"indicators: {', '.join(s.required_indicators)}")
        for k, v in s.params.items():
            print(f"    {k}: {v}")
        print()


def cmd_diagnostics(args):
    """Print the strategy diagnostics log."""
    journal_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "journal", "logs")
    diag_path = os.path.join(journal_dir, "diagnostics_summary.json")
    if not os.path.exists(diag_path):
        print(f"{Colors.RED}No diagnostics found. Run simulation first.{Colors.RESET}")
        return
        
    with open(diag_path, "r") as f:
        diag = json.load(f)
        
    print(f"\n{Colors.BOLD}--- STRATEGY DIAGNOSTICS ---{Colors.RESET}")
    print(f"Total simulated days: {diag.get('total_days')}\n")
    
    for s_name, data in diag.get("per_strategy_summary", {}).items():
        print(f"{Colors.GREEN}{Colors.BOLD}Strategy: {s_name}{Colors.RESET}")
        print(f"  Days Eligible:      {data.get('days_eligible')}")
        print(f"  Base Condition Met: {data.get('base_condition_met')}")
        print(f"  Signal Generated:   {data.get('signal_generated')}")
        print(f"  Passed Filters:     {data.get('passed_filters')}")
        print(f"  Passed Scorer:      {data.get('passed_scorer')}")
        print(f"  {Colors.YELLOW}Reason Histogram:{Colors.RESET}")
        
        hist = data.get("reason_histogram", {})
        for reason, count in sorted(hist.items(), key=lambda x: x[1], reverse=True):
            print(f"    - {reason}: {count}")
        print("")


def main():
    parser = argparse.ArgumentParser(
        description="Jack — Bank Nifty Backtesting Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", default="config/settings.yaml",
                        help="Path to config file")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # run
    p_run = subparsers.add_parser("run", help="Run simulation")
    p_run.add_argument("--split", choices=["train", "test", "holdout"],
                       default="train")
    p_run.add_argument("--verbose", action="store_true")

    # analyze
    p_analyze = subparsers.add_parser("analyze", help="Analyze last run")
    p_analyze.add_argument("--split", default="train")

    # montecarlo
    p_mc = subparsers.add_parser("montecarlo", help="Monte Carlo validation")
    p_mc.add_argument("--split", default="train")
    p_mc.add_argument("--n", type=int, default=10000)

    # walkforward
    p_wf = subparsers.add_parser("walkforward", help="Walk-forward validation")
    p_wf.add_argument("--train-years", type=int, default=2)
    p_wf.add_argument("--test-months", type=int, default=3)

    # benchmark
    p_bm = subparsers.add_parser("benchmark", help="Benchmark comparison")
    p_bm.add_argument("--split", default="train")

    # report
    p_rpt = subparsers.add_parser("report", help="Generate HTML report")
    p_rpt.add_argument("--split", default="train")
    p_rpt.add_argument("--output", default="report.html")

    # validate-data
    subparsers.add_parser("validate-data", help="Validate data files")

    # indicators
    subparsers.add_parser("indicators", help="List registered indicators")

    # strategies
    subparsers.add_parser("strategies", help="List strategies")

    # review
    p_review = subparsers.add_parser("review", help="Weekly journal review")
    p_review.add_argument("--days", type=int, default=5)

    # diagnostics
    p_diag = subparsers.add_parser("diagnostics", help="Print the strategy diagnostics log")
    p_diag.add_argument("--split", choices=["train", "test", "holdout"], default="train")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    commands = {
        "run": cmd_run,
        "analyze": cmd_analyze,
        "montecarlo": cmd_montecarlo,
        "walkforward": cmd_walkforward,
        "benchmark": cmd_benchmark,
        "report": cmd_report,
        "validate-data": cmd_validate_data,
        "indicators": cmd_indicators,
        "strategies": cmd_strategies,
        "diagnostics": cmd_diagnostics,
        "review": cmd_review,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        cmd_func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
