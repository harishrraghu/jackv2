"""
Walk-forward validation.

Rolling walk-forward optimization that tests strategy robustness
across multiple train/test windows.
"""

import pandas as pd
from collections import defaultdict


class WalkForwardValidator:
    """
    Rolling walk-forward validation.

    Tests whether strategies that perform well in training also
    perform well in subsequent out-of-sample periods.
    """

    def __init__(self, data: dict, strategies: list, config: dict):
        self.data = data
        self.strategies = strategies
        self.config = config

    def generate_windows(self, train_years: int = 2,
                         test_months: int = 3) -> list[dict]:
        """
        Generate rolling train/test window pairs.

        Args:
            train_years: Number of years for training window.
            test_months: Number of months for test window.

        Returns:
            List of window dicts with train/test date ranges.
        """
        daily = self.data.get("1d", pd.DataFrame())
        if daily.empty:
            return []

        all_dates = sorted(daily["Date"].unique())
        start = all_dates[0]
        end = all_dates[-1]

        windows = []
        train_start = pd.Timestamp(start)

        while True:
            train_end = train_start + pd.DateOffset(years=train_years) - pd.DateOffset(days=1)
            test_start = train_end + pd.DateOffset(days=1)
            test_end = test_start + pd.DateOffset(months=test_months) - pd.DateOffset(days=1)

            if test_end > pd.Timestamp(end):
                break

            windows.append({
                "train_start": train_start.strftime("%Y-%m-%d"),
                "train_end": train_end.strftime("%Y-%m-%d"),
                "test_start": test_start.strftime("%Y-%m-%d"),
                "test_end": test_end.strftime("%Y-%m-%d"),
            })

            # Slide by test_months
            train_start += pd.DateOffset(months=test_months)

        return windows

    def run(self, train_years: int = 2, test_months: int = 3) -> dict:
        """
        Run walk-forward validation.

        Returns:
            Dict with window results and strategy survival rates.
        """
        windows = self.generate_windows(train_years, test_months)

        if not windows:
            return {"error": "insufficient_data_for_walk_forward", "windows": []}

        results = []
        strategy_stats = defaultdict(lambda: {
            "windows_tested": 0,
            "profitable_train": 0,
            "profitable_test": 0,
            "profitable_both": 0,
            "degradation_ratios": [],
        })

        for window in windows:
            window_result = {
                "train_start": window["train_start"],
                "train_end": window["train_end"],
                "test_start": window["test_start"],
                "test_end": window["test_end"],
                "strategies": {},
            }

            # Note: Full simulation per window would be expensive.
            # For now, we mark this as a placeholder that the simulator
            # would fill in during actual walk-forward runs.
            for strat in self.strategies:
                name = strat if isinstance(strat, str) else strat.name
                strategy_stats[name]["windows_tested"] += 1

                window_result["strategies"][name] = {
                    "train_sharpe": None,
                    "test_sharpe": None,
                    "profitable_both": None,
                    "note": "Run simulator per window for actual results",
                }

            results.append(window_result)

        # Build summary
        strategy_summary = {}
        for name, stats in strategy_stats.items():
            tested = stats["windows_tested"]
            both = stats["profitable_both"]
            survival = both / tested if tested > 0 else 0
            avg_deg = (sum(stats["degradation_ratios"]) / len(stats["degradation_ratios"])
                       if stats["degradation_ratios"] else 0)

            strategy_summary[name] = {
                "windows_tested": tested,
                "survival_rate": round(survival, 3),
                "avg_degradation": round(avg_deg, 3),
                "robust": survival > 0.6 and avg_deg > 0.5,
            }

        return {
            "windows": results,
            "strategy_summary": strategy_summary,
            "total_windows": len(windows),
        }

    def print_report(self) -> None:
        """Print formatted walk-forward results."""
        result = self.run()

        print(f"\n{'='*60}")
        print("  WALK-FORWARD VALIDATION")
        print(f"{'='*60}")
        print(f"\n  Total windows: {result['total_windows']}")

        if result.get("windows"):
            print(f"\n  Windows:")
            for i, w in enumerate(result["windows"][:10]):  # Show first 10
                print(f"    {i+1}. Train: {w['train_start']} → {w['train_end']} | "
                      f"Test: {w['test_start']} → {w['test_end']}")

        if result.get("strategy_summary"):
            print(f"\n  Strategy Survival:")
            for name, stats in result["strategy_summary"].items():
                robust_str = "✓ ROBUST" if stats["robust"] else "✗ FRAGILE"
                print(f"    {name:25s}: survival={stats['survival_rate']:.0%} "
                      f"degradation={stats['avg_degradation']:.2f} — {robust_str}")

        print(f"\n{'='*60}")
