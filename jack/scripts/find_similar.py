"""
Find Similar Days Script — find historically similar days.

Run: python -m scripts.find_similar
"""

import os
import sys
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.similarity import SimilaritySearch

logging.basicConfig(level=logging.INFO, format="%(message)s")

CONTEXT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "data", "cache", "market_context.json")


def find_similar(gap_pct: float = None, rsi: float = None,
                  atr: float = None, regime: str = None,
                  top_n: int = 5):
    """Find similar historical days."""
    
    # Try loading context for defaults
    context = {}
    if os.path.exists(CONTEXT_FILE):
        with open(CONTEXT_FILE, "r") as f:
            context = json.load(f)
    
    # Override with args
    if gap_pct is not None: context["gap_pct"] = gap_pct
    if rsi is not None: context["rsi"] = rsi
    if atr is not None: context["atr"] = atr
    if regime is not None: context["regime"] = regime
    
    search = SimilaritySearch()
    result = search.find_similar_with_outcome(context, top_n=top_n)
    
    print(f"🔍 SIMILAR DAYS ANALYSIS")
    print(f"{'='*50}")
    print(f"  Days found: {result['days_analyzed']}")
    print(f"  Bullish: {result['bullish_count']} | "
          f"Bearish: {result['bearish_count']}")
    print(f"  Avg P&L: Rs{result['avg_pnl']:,.0f}")
    print(f"  Success Rate: {result['success_rate']:.0f}%")
    print(f"  Recommendation: {result['recommended_direction']}")
    
    print(f"\n  Similar days:")
    for day in result.get("similar_days", []):
        pnl = day.get("total_pnl", 0)
        emoji = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"
        print(f"  {emoji} {day['date']} ({day['day_of_week']}): "
              f"gap={day.get('gap_pct', 'N/A'):.2f}%, "
              f"fh={day.get('fh_return_pct', 'N/A')}, "
              f"pnl=Rs{pnl:,.0f} "
              f"(dist={day['distance']:.3f})")
    
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--gap", type=float, default=None)
    parser.add_argument("--rsi", type=float, default=None)
    parser.add_argument("--atr", type=float, default=None)
    parser.add_argument("--regime", default=None)
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()
    find_similar(args.gap, args.rsi, args.atr, args.regime, args.top)
