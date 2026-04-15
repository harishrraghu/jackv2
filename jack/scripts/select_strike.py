"""
Select Strike Script — pick best option strike for a trade.

Run: python -m scripts.select_strike --direction LONG --spot 52100
"""

import os
import sys
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.strike_selector import StrikeSelectorV2

logging.basicConfig(level=logging.INFO, format="%(message)s")

CONTEXT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "data", "cache", "market_context.json")


def select_strike(direction: str = "LONG", spot: float = None,
                   symbol: str = "BANKNIFTY"):
    """Select best strike from available data."""
    
    # Load context if spot not provided
    if spot is None:
        if os.path.exists(CONTEXT_FILE):
            with open(CONTEXT_FILE, "r") as f:
                context = json.load(f)
            spot = context.get("spot", 0)
    
    if not spot or spot <= 0:
        # Try live fetch
        try:
            from data.dhan_fetcher import DhanFetcher
            fetcher = DhanFetcher(symbol=symbol)
            spot = fetcher.get_spot_price()
        except Exception:
            pass
    
    if not spot or spot <= 0:
        print("[ERR] No spot price available. Pass --spot or configure Dhan.")
        return None
    
    print(f"🎯 STRIKE SELECTION: {direction}")
    print(f"{'='*50}")
    print(f"  Spot: Rs{spot:,.2f}")
    
    selector = StrikeSelectorV2()
    
    # Try to get live chain
    chain = None
    try:
        from data.dhan_fetcher import DhanFetcher
        from data.dhan_client import DhanClient
        client = DhanClient()
        if client.is_configured():
            fetcher = DhanFetcher(symbol=symbol)
            expiry = fetcher.get_nearest_expiry()
            if expiry:
                chain = fetcher.get_option_chain_df(expiry=expiry)
                dte = fetcher.get_days_to_expiry(expiry)
                print(f"  Expiry: {expiry} ({dte:.1f} days)")
    except Exception:
        pass
    
    result = selector.select_best(chain, spot, direction)
    
    print(f"\n  [OK] Recommended: {int(result['strike'])} {result['option_type']}")
    print(f"  Moneyness: {result.get('moneyness', 'N/A')}")
    
    if result.get("premium", 0) > 0:
        print(f"  Premium: Rs{result['premium']:.2f}")
        print(f"  Lot Cost: Rs{result.get('lot_cost', 0):,.2f}")
        print(f"  Delta: {result.get('delta', 0):.3f}")
        print(f"  Theta: {result.get('theta', 0):.2f}")
        print(f"  IV: {result.get('iv', 0):.2f}%")
        print(f"  OI: {result.get('oi', 0):,}")
        print(f"  Score: {result.get('score', 0):.3f}")
        
        if result.get("suggested_sl"):
            print(f"\n  SL: Rs{result['suggested_sl']:.2f}")
            print(f"  Target: Rs{result['suggested_target']:.2f}")
            print(f"  R:R: {result.get('risk_reward', 'N/A')}")
    else:
        print("  [!]️  Using fallback selection (no chain data)")
    
    print(f"\n{json.dumps(result, indent=2, default=str)}")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--direction", default="LONG", choices=["LONG", "SHORT"])
    parser.add_argument("--spot", type=float, default=None)
    parser.add_argument("--symbol", default="BANKNIFTY")
    args = parser.parse_args()
    select_strike(args.direction, args.spot, args.symbol)
