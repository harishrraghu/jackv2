"""
Walk-forward validation.

Rolling walk-forward optimization that tests strategy robustness
across multiple train/test windows by running actual simulations.
"""

import os
import copy
import tempfile

import pandas as pd
import numpy as np
import yaml


class WalkForwardValidator:
    """
    Rolling walk-forward validation.

    Tests whether strategies that perform well in training also
    perform well in subsequent out-of-sample periods by running
    full simulations per window.
    """

    def __init__(self, config: dict, config_path: str):
        """
        Initialize walk-forward validator.

        Args:
            config: Full config dict (from settings.yaml).
            config_path: Path to the original config file (for Simulator).
        """
        self.config = config
        self.config_path = config_path

        # Resolve base_dir from config_path for data loading
        if os.path.isabs(config_path):
            self.base_dir = os.path.dirname(os.path.dirname(config_path))
        else:
            self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
        # Load daily data to find date range
        from data.loader import load_all_timeframes
        data_path = os.path.join(self.base_dir, self.config["data"]["base_path"])
        data = load_all_timeframes(data_path)
        daily = data.get("1d", pd.DataFrame())

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
        Run walk-forward validation with actual simulation per window.

        Returns:
            Dict with window results, survival rate, and degradation ratio.
        """
        from engine.simulator import Simulator

        windows = self.generate_windows(train_years, test_months)

        if not windows:
            return {"error": "insufficient_data", "windows": []}

        results = []

        for i, window in enumerate(windows):
            print(f"  Window {i+1}/{len(windows)}: "
                  f"Train {window['train_start']}->{window['train_end']} | "
                  f"Test {window['test_start']}->{window['test_end']}")

            # Create a temporary config with this window's dates
            temp_config = copy.deepcopy(self.config)
            temp_config["splits"]["train"]["start"] = window["train_start"]
            temp_config["splits"]["train"]["end"] = window["train_end"]
            temp_config["splits"]["test"]["start"] = window["test_start"]
            temp_config["splits"]["test"]["end"] = window["test_end"]

            # Write temp config
            temp_dir = tempfile.mkdtemp()
            temp_path = os.path.join(temp_dir, "settings.yaml")
            with open(temp_path, "w") as f:
                yaml.dump(temp_config, f)

            try:
                # Run train simulation
                sim = Simulator(config_path=temp_path)
                train_results = sim.run(split="train", verbose=False)

                # Run test simulation
                sim2 = Simulator(config_path=temp_path)
                test_results = sim2.run(split="test", verbose=False)

                train_sharpe = train_results.get("sharpe_ratio", 0)
                test_sharpe = test_results.get("sharpe_ratio", 0)

                window_result = {
                    **window,
                    "train_trades": train_results.get("total_trades", 0),
                    "train_win_rate": train_results.get("win_rate", 0),
                    "train_pnl": train_results.get("net_pnl", 0),
                    "train_sharpe": train_sharpe,
                    "test_trades": test_results.get("total_trades", 0),
                    "test_win_rate": test_results.get("win_rate", 0),
                    "test_pnl": test_results.get("net_pnl", 0),
                    "test_sharpe": test_sharpe,
                    "degradation_ratio": (
                        test_sharpe / train_sharpe
                        if train_sharpe > 0 else 0
                    ),
                }
            except Exception as e:
                print(f"    [ERROR] Window {i+1} failed: {e}")
                window_result = {
                    **window,
                    "train_trades": 0, "train_win_rate": 0,
                    "train_pnl": 0, "train_sharpe": 0,
                    "test_trades": 0, "test_win_rate": 0,
                    "test_pnl": 0, "test_sharpe": 0,
                    "degradation_ratio": 0,
                    "error": str(e),
                }
            finally:
                # Clean up temp files
                try:
                    os.remove(temp_path)
                    os.rmdir(temp_dir)
                except OSError:
                    pass

            results.append(window_result)

        # Compute survival rate
        valid_results = [r for r in results if "error" not in r]
        profitable_both = sum(
            1 for r in valid_results
            if r["train_pnl"] > 0 and r["test_pnl"] > 0
        )
        survival_rate = profitable_both / len(valid_results) if valid_results else 0
        avg_degradation = (
            np.mean([r["degradation_ratio"] for r in valid_results])
            if valid_results else 0
        )

        return {
            "windows": results,
            "total_windows": len(results),
            "survival_rate": round(survival_rate, 3),
            "avg_degradation_ratio": round(float(avg_degradation), 3),
            "robust": survival_rate > 0.6 and float(avg_degradation) > 0.5,
        }

    def print_report(self) -> None:
        """Print formatted walk-forward results."""
        result = self.run()

        print(f"\n{'='*60}")
        print("  WALK-FORWARD VALIDATION")
        print(f"{'='*60}")
        print(f"\n  Total windows: {result['total_windows']}")

        if result.get("windows"):
            print(f"\n  {'Window':<8} {'Train Period':<27} {'Test Period':<27} "
                  f"{'Train PnL':>12} {'Test PnL':>12} {'Deg Ratio':>10}")
            print(f"  {'-'*8} {'-'*27} {'-'*27} {'-'*12} {'-'*12} {'-'*10}")

            for i, w in enumerate(result["windows"]):
                train_period = f"{w['train_start']} -> {w['train_end']}"
                test_period = f"{w['test_start']} -> {w['test_end']}"
                train_pnl = w.get("train_pnl", 0)
                test_pnl = w.get("test_pnl", 0)
                deg = w.get("degradation_ratio", 0)

                pnl_indicator = "✓" if test_pnl > 0 else "✗"
                print(f"  {i+1:<8} {train_period:<27} {test_period:<27} "
                      f"Rs{train_pnl:>+10,.0f} Rs{test_pnl:>+10,.0f} "
                      f"{deg:>8.2f}  {pnl_indicator}")

        print(f"\n  Survival Rate: {result.get('survival_rate', 0):.1%} "
              f"(profitable in both train & test)")
        print(f"  Avg Degradation Ratio: {result.get('avg_degradation_ratio', 0):.3f}")

        robust = result.get("robust", False)
        if robust:
            print(f"\n  ✓ SYSTEM IS ROBUST (survival > 60%, degradation > 0.5)")
        else:
            print(f"\n  ✗ SYSTEM MAY BE FRAGILE (needs more analysis)")

        print(f"{'='*60}")
