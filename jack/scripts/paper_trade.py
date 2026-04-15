"""
Paper Trade Script — place a paper trade order.

Run: python -m scripts.paper_trade --action BUY --strike 52100 --type CE --premium 285
"""

import os
import sys
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.paper_trader_v2 import PaperTradingEngine

logging.basicConfig(level=logging.INFO, format="%(message)s")


def paper_trade(action: str, strike: float, option_type: str,
                premium: float, lots: int = 1,
                sl: float = None, target: float = None,
                strategy: str = ""):
    """Place a paper trade."""
    engine = PaperTradingEngine()
    
    print(f"📝 PAPER TRADE")
    print(f"{'='*50}")
    
    result = engine.place_order(
        direction=action,
        strike=strike,
        option_type=option_type,
        premium=premium,
        lots=lots,
        stop_loss=sl,
        target=target,
        strategy=strategy,
    )
    
    if result["status"] == "PLACED":
        pos = result["position"]
        print(f"  [OK] ORDER PLACED")
        print(f"  {action} {lots}L {int(strike)}{option_type} @ Rs{premium:.2f}")
        print(f"  SL: Rs{pos['stop_loss']:.2f} | Target: Rs{pos['target']:.2f}")
        print(f"  Position ID: {pos['id']}")
    else:
        print(f"  [ERR] ORDER REJECTED: {result['reason']}")
    
    # Show portfolio summary
    summary = engine.get_summary()
    print(f"\n📊 Portfolio:")
    print(f"  Capital: Rs{summary['current_capital']:,.2f}")
    print(f"  Open Positions: {summary['open_positions']}")
    print(f"  Daily P&L: Rs{summary['daily_pnl']:,.2f}")
    
    print(f"\n{json.dumps(result, indent=2, default=str)}")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True, choices=["BUY", "SELL"])
    parser.add_argument("--strike", type=float, required=True)
    parser.add_argument("--type", dest="option_type", default="CE", choices=["CE", "PE"])
    parser.add_argument("--premium", type=float, required=True)
    parser.add_argument("--lots", type=int, default=1)
    parser.add_argument("--sl", type=float, default=None)
    parser.add_argument("--target", type=float, default=None)
    parser.add_argument("--strategy", default="manual")
    args = parser.parse_args()
    
    paper_trade(args.action, args.strike, args.option_type,
                args.premium, args.lots, args.sl, args.target, args.strategy)
