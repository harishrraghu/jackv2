"""
Post-Market Review Script — end-of-day analysis and journaling.

Run: python -m scripts.post_market
"""

import os
import sys
import json
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.paper_trader_v2 import PaperTradingEngine

logging.basicConfig(level=logging.INFO, format="%(message)s")

CONTEXT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "data", "cache", "market_context.json")


def post_market():
    """Run post-market review."""
    
    print("=" * 60)
    print(f"📊 JACK PRO — POST-MARKET REVIEW ({datetime.now().strftime('%Y-%m-%d')})")
    print("=" * 60)
    
    # Load morning context
    context = {}
    if os.path.exists(CONTEXT_FILE):
        with open(CONTEXT_FILE, "r") as f:
            context = json.load(f)
    
    # Get paper trading results
    engine = PaperTradingEngine()
    summary = engine.get_summary()
    
    print(f"\n💰 DAY SUMMARY:")
    print(f"  Paper P&L: Rs{summary['daily_pnl']:,.2f}")
    print(f"  Trades: {summary.get('closed_positions_today', 0)} closed, "
          f"{summary['open_positions']} still open")
    print(f"  Capital: Rs{summary['current_capital']:,.2f} "
          f"({summary['total_return_pct']:+.2f}%)")
    
    # Close any remaining positions
    if summary['open_positions'] > 0:
        print(f"\n  [!]️  Closing {summary['open_positions']} open positions...")
        closed = engine.close_all(reason="end_of_day")
        for c in closed:
            pos = c.get("position", {})
            print(f"    Closed {pos.get('symbol', '')}: P&L Rs{c.get('pnl', 0):,.2f}")
    
    # Show trade history
    trades = engine.get_trade_history(n=10)
    today = datetime.now().strftime("%Y-%m-%d")
    today_trades = [t for t in trades if t.get("entry_date") == today]
    
    if today_trades:
        print(f"\n📋 TODAY'S TRADES:")
        for t in today_trades:
            emoji = "[OK]" if t.get("realized_pnl", 0) >= 0 else "[ERR]"
            print(f"  {emoji} {t['direction']} {t.get('symbol', '')} "
                  f"({t.get('strategy', 'manual')})")
            print(f"    Entry: Rs{t['entry_premium']:.2f} -> "
                  f"Exit: Rs{t.get('exit_premium', 0):.2f}")
            print(f"    P&L: Rs{t.get('realized_pnl', 0):,.2f} | "
                  f"Exit reason: {t.get('exit_reason', 'N/A')}")
    else:
        print("\n  No trades today.")
    
    # Morning thesis review
    thesis = context.get("morning_thesis", "")
    if thesis:
        print(f"\n📝 MORNING THESIS WAS:")
        print(f"  \"{thesis}\"")
        
        confluence = context.get("confluence", {})
        print(f"\n  Predicted: {confluence.get('direction', 'N/A')} "
              f"({confluence.get('conviction_level', 'N/A')})")
    
    # Save day summary
    day_summary = {
        "date": today,
        "paper_pnl": summary["daily_pnl"],
        "trades_count": len(today_trades),
        "capital": summary["current_capital"],
        "morning_thesis": thesis,
        "confluence_direction": context.get("confluence", {}).get("direction"),
        "confluence_conviction": context.get("confluence", {}).get("conviction"),
        "trades": today_trades,
        "reviewed_at": datetime.now().isoformat(),
    }
    
    cache_dir = os.path.dirname(CONTEXT_FILE)
    os.makedirs(cache_dir, exist_ok=True)
    summary_file = os.path.join(cache_dir, f"day_summary_{today}.json")
    
    with open(summary_file, "w") as f:
        json.dump(day_summary, f, indent=2, default=str)
    
    print(f"\n💾 Day summary saved to {summary_file}")
    
    # Reset for next day
    print("\n🔄 Resetting for next day...")
    engine.reset_daily()
    
    return day_summary


if __name__ == "__main__":
    post_market()
