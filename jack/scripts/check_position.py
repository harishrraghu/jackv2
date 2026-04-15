"""
Check Position Script — check if SL/target hit on open positions.

Run: python -m scripts.check_position
"""

import os
import sys
import json
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.paper_trader_v2 import PaperTradingEngine
from engine.position_monitor import PositionMonitor

logging.basicConfig(level=logging.INFO, format="%(message)s")


def check_position(symbol: str = "BANKNIFTY"):
    """Check all open paper positions against live prices."""
    engine = PaperTradingEngine()
    monitor = PositionMonitor(engine)
    
    print(f"📊 POSITION CHECK ({datetime.now().strftime('%H:%M')})")
    print(f"{'='*50}")
    
    if not engine.open_positions:
        print("  No open positions.")
        summary = engine.get_summary()
        if summary["daily_pnl"] != 0:
            print(f"  Today's P&L: Rs{summary['daily_pnl']:,.2f}")
        return {"status": "no_positions"}
    
    # Try to get live prices
    current_prices = {}
    try:
        from data.dhan_client import DhanClient
        from data.dhan_fetcher import DhanFetcher
        
        client = DhanClient()
        if client.is_configured():
            fetcher = DhanFetcher(symbol=symbol)
            expiry = fetcher.get_nearest_expiry()
            if expiry:
                chain = fetcher.get_option_chain_df(expiry=expiry)
                if chain is not None:
                    for _, row in chain.iterrows():
                        strike = int(row["strike"])
                        if row.get("ce_ltp", 0) > 0:
                            current_prices[f"{strike}CE"] = row["ce_ltp"]
                        if row.get("pe_ltp", 0) > 0:
                            current_prices[f"{strike}PE"] = row["pe_ltp"]
    except Exception as e:
        print(f"  [!]️  Could not fetch live prices: {e}")
    
    # Check positions
    result = monitor.check_positions(current_prices)
    
    # Display
    for pos in result.get("positions", []):
        emoji = "🟢" if pos["pnl"] >= 0 else "🔴"
        print(f"\n  {emoji} {pos['direction']} {pos['symbol']}")
        print(f"    Entry: Rs{pos['entry']:.2f} -> Current: Rs{pos['current']:.2f}")
        print(f"    P&L: Rs{pos['pnl']:,.2f} ({pos['pnl_pct']:+.1f}%)")
        print(f"    SL: Rs{pos['sl']:.2f} | Target: Rs{pos['target']:.2f}")
    
    if result.get("exits_triggered"):
        print(f"\n  ⚡ EXITS TRIGGERED:")
        for exit_info in result["exits_triggered"]:
            print(f"    {exit_info.get('reason', 'unknown')}: "
                  f"P&L Rs{exit_info.get('pnl', 0):,.2f}")
    
    print(f"\n  Daily P&L: Rs{result.get('daily_pnl', 0):,.2f}")
    print(f"  Unrealized: Rs{result.get('unrealized_pnl', 0):,.2f}")
    
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BANKNIFTY")
    args = parser.parse_args()
    check_position(args.symbol)
