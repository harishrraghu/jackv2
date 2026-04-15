"""
Live Check Script — check current market state at any time during the day.

Run: python -m scripts.live_check
     python -m scripts.live_check --time 10:15
"""

import os
import sys
import json
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.confluence import ConfluenceScorer
from engine.entry_checklist import EntryChecklist

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

CONTEXT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "data", "cache", "market_context.json")


def live_check(time_override: str = None, symbol: str = "BANKNIFTY"):
    """
    Check current market state and update context.
    
    Args:
        time_override: Override current time (for testing).
        symbol: Underlying symbol.
    """
    current_time = time_override or datetime.now().strftime("%H:%M")
    
    print("=" * 60)
    print(f"🔍 JACK PRO — LIVE CHECK ({current_time})")
    print("=" * 60)
    
    # Load morning context if available
    context = {}
    if os.path.exists(CONTEXT_FILE):
        with open(CONTEXT_FILE, "r") as f:
            context = json.load(f)
        print(f"  Loaded morning context from {context.get('date', 'unknown')}")
    
    # Try live data
    try:
        from data.dhan_client import DhanClient
        client = DhanClient()
        
        if client.is_configured():
            from data.dhan_fetcher import DhanFetcher
            from indicators.oi_analysis import OIAnalyzer
            
            fetcher = DhanFetcher(symbol=symbol)
            spot = fetcher.get_spot_price()
            
            if spot:
                print(f"\n📊 LIVE DATA:")
                print(f"  Spot: Rs{spot:,.2f}")
                context["spot"] = spot
                
                ohlc = fetcher.get_spot_ohlc()
                if ohlc:
                    day_change = ((ohlc.get("ltp", 0) - ohlc.get("open", 0)) / 
                                  ohlc.get("open", 1) * 100)
                    print(f"  Open: Rs{ohlc['open']:,.2f} | "
                          f"High: Rs{ohlc['high']:,.2f} | "
                          f"Low: Rs{ohlc['low']:,.2f}")
                    print(f"  Day Change: {day_change:+.2f}%")
                
                # Update OI data
                expiry = fetcher.get_nearest_expiry()
                if expiry:
                    chain = fetcher.get_option_chain_df(expiry=expiry)
                    if chain is not None:
                        analyzer = OIAnalyzer()
                        oi_result = analyzer.full_analysis(chain, spot)
                        
                        pcr = oi_result.get("pcr_oi", {})
                        print(f"\n📈 OI ANALYSIS:")
                        print(f"  PCR: {pcr.get('pcr', 'N/A')} "
                              f"({pcr.get('interpretation', '')})")
                        
                        max_pain = oi_result.get("max_pain", {})
                        print(f"  Max Pain: Rs{max_pain.get('max_pain', 0):,.0f} "
                              f"(pull: {max_pain.get('pull_direction', 'N/A')})")
                        
                        buildup = oi_result.get("buildup", {})
                        print(f"  OI Buildup: {buildup.get('classification', 'N/A')} "
                              f"(signal: {buildup.get('signal', 'N/A')})")
                        
                        levels = oi_result.get("oi_levels", {})
                        imm = levels.get("immediate_range", {})
                        if imm:
                            print(f"  OI Range: Rs{imm.get('lower', 0):,.0f} — "
                                  f"Rs{imm.get('upper', 0):,.0f}")
                        
                        context.update({
                            "pcr": pcr,
                            "max_pain": max_pain,
                            "oi_buildup": buildup,
                            "oi_levels": levels,
                        })
            else:
                print("  [!]️  Market may be closed. No live data.")
        else:
            print("  ℹ️  Dhan not configured. Using cached data only.")
    except Exception as e:
        print(f"  [!]️  Live data error: {e}")
    
    # Update time
    context["current_time"] = current_time
    
    # Recompute confluence
    print(f"\n🧮 CONFLUENCE UPDATE:")
    scorer = ConfluenceScorer()
    confluence = scorer.score(context)
    
    direction = confluence["direction"]
    conviction = confluence["conviction"]
    arrow = "⬆️" if direction == "LONG" else "⬇️" if direction == "SHORT" else "➡️"
    
    print(f"  {arrow} {direction} (conviction: {conviction:.3f} "
          f"— {confluence['conviction_level']})")
    
    # Run entry checklist
    if direction != "NEUTRAL" and conviction >= 0.15:
        print(f"\n[OK] ENTRY CHECKLIST ({direction}):")
        checklist = EntryChecklist()
        result = checklist.evaluate(direction, context)
        
        for gate in result["gates"]:
            status = "[OK]" if gate["passed"] else "[ERR]"
            print(f"  {status} {gate['name']}: {gate['reason']}")
        
        print(f"\n  Result: {'GO [OK]' if result['all_passed'] else 'NO-GO [ERR]'} "
              f"({result['passed_count']}/{result['total_gates']})")
        
        if result["failed_gates"]:
            print(f"  Failed: {', '.join(result['failed_gates'])}")
    else:
        print(f"\n  ℹ️  No trade signal (conviction too low or neutral)")
    
    # Save updated context
    serializable = {k: v for k, v in context.items() if k != "option_chain"}
    try:
        with open(CONTEXT_FILE, "w") as f:
            json.dump(serializable, f, indent=2, default=str)
    except Exception:
        pass
    
    print()
    return context


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Jack Pro Live Check")
    parser.add_argument("--time", default=None)
    parser.add_argument("--symbol", default="BANKNIFTY")
    args = parser.parse_args()
    
    live_check(time_override=args.time, symbol=args.symbol)
