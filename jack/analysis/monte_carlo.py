"""
Monte Carlo significance testing.

Tests whether trading results are statistically significant through:
1. Shuffle test — does trade sequence matter?
2. Bootstrap confidence intervals — how robust are the metrics?
"""

import numpy as np
import math


class MonteCarloValidator:
    """
    Validate trading results through Monte Carlo simulation.

    Shuffle test: checks if the edge is real or just lucky sequencing.
    Bootstrap: provides confidence intervals for key metrics.
    """

    def __init__(self, trades: list[dict], initial_capital: float,
                 n_simulations: int = 10000):
        self.trades = trades
        self.initial_capital = initial_capital
        self.n_simulations = n_simulations
        self.pnls = [t.get("net_pnl", 0) for t in trades]

    def run_shuffle_test(self) -> dict:
        """
        Test if trade sequence matters or if random ordering gives similar results.

        Shuffles trade P&Ls 10,000 times and compares against actual sequence.
        """
        if not self.pnls or len(self.pnls) < 5:
            return {"error": "insufficient_trades", "actual_final_equity": 0}

        pnls = np.array(self.pnls)

        # Actual sequence results
        actual_equity = self.initial_capital + np.cumsum(pnls)
        actual_final = float(actual_equity[-1])
        actual_peak = float(np.maximum.accumulate(np.concatenate(
            [[self.initial_capital], actual_equity]
        )).max())
        actual_dd = float((actual_peak - actual_equity.min()) / actual_peak * 100)

        # Shuffle simulations
        shuffled_finals = np.zeros(self.n_simulations)
        shuffled_dds = np.zeros(self.n_simulations)

        rng = np.random.RandomState(42)
        for i in range(self.n_simulations):
            shuffled = rng.permutation(pnls)
            equity = self.initial_capital + np.cumsum(shuffled)
            shuffled_finals[i] = equity[-1]

            peak = np.maximum.accumulate(
                np.concatenate([[self.initial_capital], equity])
            ).max()
            dd = (peak - equity.min()) / peak * 100 if peak > 0 else 0
            shuffled_dds[i] = dd

        p_value = float(np.mean(shuffled_finals >= actual_final))
        percentile_rank = float(np.mean(shuffled_finals <= actual_final) * 100)

        return {
            "actual_final_equity": round(actual_final, 2),
            "mean_shuffled_equity": round(float(np.mean(shuffled_finals)), 2),
            "p_value": round(p_value, 4),
            "percentile_rank": round(percentile_rank, 1),
            "actual_max_drawdown": round(actual_dd, 2),
            "mean_shuffled_drawdown": round(float(np.mean(shuffled_dds)), 2),
            "worst_shuffled_drawdown_95": round(float(np.percentile(shuffled_dds, 95)), 2),
            "interpretation": self._interpret_shuffle(percentile_rank),
        }

    def run_bootstrap_confidence(self) -> dict:
        """
        Bootstrap confidence intervals for win_rate, profit_factor, and Sharpe.
        """
        if not self.pnls or len(self.pnls) < 5:
            return {"error": "insufficient_trades"}

        pnls = np.array(self.pnls)
        n = len(pnls)

        win_rates = np.zeros(self.n_simulations)
        profit_factors = np.zeros(self.n_simulations)
        sharpes = np.zeros(self.n_simulations)

        rng = np.random.RandomState(42)
        for i in range(self.n_simulations):
            sample = rng.choice(pnls, size=n, replace=True)

            wins = sample[sample > 0]
            losses = sample[sample <= 0]

            win_rates[i] = len(wins) / n * 100 if n > 0 else 0

            sum_wins = wins.sum() if len(wins) > 0 else 0
            sum_losses = abs(losses.sum()) if len(losses) > 0 else 0
            profit_factors[i] = sum_wins / sum_losses if sum_losses > 0 else 10.0

            std = np.std(sample, ddof=1) if len(sample) > 1 else 1
            mean = np.mean(sample)
            sharpes[i] = (mean / std * math.sqrt(252)) if std > 0 else 0

        return {
            "win_rate": self._percentiles(win_rates),
            "profit_factor": self._percentiles(profit_factors),
            "sharpe": self._percentiles(sharpes),
        }

    def _percentiles(self, arr: np.ndarray) -> dict:
        """Compute percentile breakdown."""
        return {
            "p5": round(float(np.percentile(arr, 5)), 3),
            "p25": round(float(np.percentile(arr, 25)), 3),
            "p50": round(float(np.percentile(arr, 50)), 3),
            "p75": round(float(np.percentile(arr, 75)), 3),
            "p95": round(float(np.percentile(arr, 95)), 3),
        }

    def _interpret_shuffle(self, percentile: float) -> str:
        """Human-readable interpretation of shuffle test."""
        if percentile > 95:
            return "STRONG EDGE: Results are significantly better than random. Edge is likely real."
        elif percentile > 75:
            return "MODERATE EDGE: Results are better than most random orderings. Edge may exist."
        elif percentile > 40:
            return "NO EDGE: Performance is indistinguishable from random. No sequence-dependent edge detected."
        else:
            return "NEGATIVE: Performance is WORSE than random ordering. Strategy may be harmful."

    def print_report(self) -> None:
        """Print formatted Monte Carlo results."""
        print(f"\n{'='*60}")
        print("  MONTE CARLO VALIDATION")
        print(f"{'='*60}")

        shuffle = self.run_shuffle_test()
        if "error" in shuffle:
            print(f"  Error: {shuffle['error']}")
            return

        print(f"\n  Shuffle Test ({self.n_simulations:,} simulations):")
        print(f"    Actual final equity:     ₹{shuffle['actual_final_equity']:,.0f}")
        print(f"    Mean shuffled equity:    ₹{shuffle['mean_shuffled_equity']:,.0f}")
        print(f"    Percentile rank:         {shuffle['percentile_rank']:.1f}%")
        print(f"    p-value:                 {shuffle['p_value']:.4f}")
        print(f"    Actual max drawdown:     {shuffle['actual_max_drawdown']:.2f}%")
        print(f"    95th pct shuffle DD:     {shuffle['worst_shuffled_drawdown_95']:.2f}%")
        print(f"\n    → {shuffle['interpretation']}")

        bootstrap = self.run_bootstrap_confidence()
        if "error" not in bootstrap:
            print(f"\n  Bootstrap Confidence Intervals:")
            for metric, pctiles in bootstrap.items():
                print(f"    {metric:20s}: "
                      f"5th={pctiles['p5']:.2f}  "
                      f"50th={pctiles['p50']:.2f}  "
                      f"95th={pctiles['p95']:.2f}")

        print(f"\n{'='*60}")
