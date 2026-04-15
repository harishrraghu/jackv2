"""
A/B Test: EMA Crossover Confidence Filter

Runs the train split twice:
  A) use_ema_filter = True  (current default)
  B) use_ema_filter = False (no EMA penalty)

Compares: total trades, win rate, net P&L, Sharpe, max drawdown.
Prints a clear verdict: "Keep filter" or "Remove filter".
"""

import os
import sys
import copy
import tempfile

import yaml

# Ensure jack directory is in the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_variant(label: str, use_ema_filter: bool, config_path: str) -> dict:
    """Run a single variant of the backtest."""
    from engine.simulator import Simulator

    print(f"\n{'='*50}")
    print(f"  Running Variant {label}: use_ema_filter = {use_ema_filter}")
    print(f"{'='*50}")

    # The Simulator reads config from file; we need to temporarily patch
    # the first_hour_verdict strategy's params after construction
    sim = Simulator(config_path=config_path)

    # Patch the strategy parameter
    fhv = sim.strategies.get("first_hour_verdict")
    if fhv:
        fhv.params["use_ema_filter"] = use_ema_filter

    results = sim.run(split="train", verbose=False)
    return results


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config", "settings.yaml")

    # Run both variants
    results_a = run_variant("A (EMA filter ON)", True, config_path)
    results_b = run_variant("B (EMA filter OFF)", False, config_path)

    # Compare
    metrics = [
        ("Total Trades", "total_trades", "d"),
        ("Win Rate (%)", "win_rate", ".1f"),
        ("Net P&L (Rs)", "net_pnl", ",.0f"),
        ("Return (%)", "return_pct", ".2f"),
        ("Max Drawdown (%)", "max_drawdown_pct", ".2f"),
        ("Sharpe Ratio", "sharpe_ratio", ".3f"),
        ("Profit Factor", "profit_factor", ".3f"),
    ]

    print(f"\n{'='*70}")
    print(f"  A/B TEST RESULTS: EMA CROSSOVER CONFIDENCE FILTER")
    print(f"{'='*70}")
    print(f"\n  {'Metric':<22} {'A (EMA ON)':>15} {'B (EMA OFF)':>15} {'Delta':>12}")
    print(f"  {'-'*22} {'-'*15} {'-'*15} {'-'*12}")

    for label, key, fmt in metrics:
        val_a = results_a.get(key, 0)
        val_b = results_b.get(key, 0)

        if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
            delta = val_b - val_a
            delta_str = f"{delta:+{fmt}}"
        else:
            delta_str = "N/A"

        print(f"  {label:<22} {val_a:>{15}{fmt}} {val_b:>{15}{fmt}} {delta_str:>12}")

    # By-strategy breakdown for first_hour_verdict
    print(f"\n  First Hour Verdict Breakdown:")
    for variant_name, res in [("A (ON)", results_a), ("B (OFF)", results_b)]:
        fhv = res.get("by_strategy", {}).get("first_hour_verdict", {})
        print(f"    {variant_name}: {fhv.get('trades', 0)} trades, "
              f"WR: {fhv.get('win_rate', 0):.1f}%, "
              f"P&L: Rs{fhv.get('pnl', 0):+,.0f}")

    # Verdict
    pnl_a = results_a.get("net_pnl", 0)
    pnl_b = results_b.get("net_pnl", 0)
    dd_a = results_a.get("max_drawdown_pct", 0)
    dd_b = results_b.get("max_drawdown_pct", 0)

    pnl_improvement = (pnl_b - pnl_a) / abs(pnl_a) * 100 if pnl_a != 0 else 0
    dd_worsened = dd_b > dd_a * 1.5  # Significantly worsened if drawdown 50%+ higher

    print(f"\n  P&L Change: {pnl_improvement:+.1f}%")
    print(f"  Drawdown Worsened Significantly: {'YES' if dd_worsened else 'NO'}")

    if pnl_improvement > 5 and not dd_worsened:
        print(f"\n  ✓ VERDICT: REMOVE the EMA filter (P&L improves >{pnl_improvement:.1f}% "
              f"without significant drawdown increase)")
    elif pnl_improvement < -5:
        print(f"\n  ✓ VERDICT: KEEP the EMA filter (removing it hurts P&L by {abs(pnl_improvement):.1f}%)")
    else:
        print(f"\n  ○ VERDICT: INCONCLUSIVE — difference is within noise "
              f"({pnl_improvement:+.1f}% P&L change). Keep current setting.")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
