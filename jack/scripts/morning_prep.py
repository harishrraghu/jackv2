"""
Morning Prep Script — the first thing Jack runs each morning.

Fetches all required data, computes indicators, builds market context,
runs confluence scoring and similarity search, and outputs a full
morning briefing.

Run: python -m scripts.morning_prep
"""

import os
import sys
import json
import logging
from datetime import datetime, date

# Add jack/ to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain.market_context import MarketContextBuilder
from engine.entry_checklist import EntryChecklist
from analysis.similarity import SimilaritySearch
from data.event_calendar import EventCalendar
from brain.core import IntelligentBrain

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Output path
CONTEXT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                            "..", "data", "cache")


def morning_prep(symbol: str = "BANKNIFTY", mode: str = "auto"):
    """
    Run the complete morning preparation routine.
    
    Args:
        symbol: Underlying to analyze.
        mode: "live" for Dhan API, "backtest" for simulation, "auto" to detect.
    """
    print("=" * 60)
    print(f"🌅 JACK PRO — MORNING PREP ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    print("=" * 60)
    
    # Detect mode
    if mode == "auto":
        from data.dhan_client import DhanClient
        client = DhanClient()
        mode = "live" if client.is_configured() else "backtest"
    
    print(f"Mode: {mode.upper()}")
    print()
    
    # =========================================================================
    # Step 1: Event Calendar
    # =========================================================================
    print("📅 Step 1: Checking Event Calendar...")
    event_cal = EventCalendar()
    today_event = event_cal.get_event_for_date()
    event_mult = event_cal.get_impact_multiplier()
    
    print(f"  Event: {today_event['name']} (impact={today_event['impact']})")
    if today_event.get("advice"):
        print(f"  [!]️  {today_event['advice']}")
    if today_event.get("is_expiry"):
        expiry_type = "Monthly" if today_event.get("is_monthly_expiry") else "Weekly"
        print(f"  📌 {expiry_type} Expiry Day")
    print(f"  Position multiplier: {event_mult}")
    print()
    
    # Check if trading is blocked
    blocked, block_reason = event_cal.is_trading_blocked()
    if blocked:
        print(f"🚫 TRADING BLOCKED: {block_reason}")
        return {"blocked": True, "reason": block_reason}
    
    # =========================================================================
    # Step 2: Fetch Market Data
    # =========================================================================
    context = {}
    
    if mode == "live":
        print(f"📡 Step 2: Fetching live data for {symbol}...")
        builder = MarketContextBuilder(mode="live")
        context = builder.build_live(symbol=symbol)
        
        spot = context.get("spot")
        if spot:
            print(f"  Spot: Rs{spot:,.2f}")
        
        ohlc = context.get("spot_ohlc", {})
        if ohlc:
            print(f"  Open: Rs{ohlc.get('open', 0):,.2f} | "
                  f"High: Rs{ohlc.get('high', 0):,.2f} | "
                  f"Low: Rs{ohlc.get('low', 0):,.2f}")
        
        if context.get("expiry"):
            print(f"  Nearest Expiry: {context['expiry']} "
                  f"({context.get('days_to_expiry', 0):.1f} days)")
        
        # OI Summary
        pcr = context.get("pcr", {})
        if pcr.get("pcr"):
            print(f"  PCR: {pcr['pcr']:.3f} ({pcr.get('interpretation', '')})")
        
        max_pain = context.get("max_pain", {})
        if max_pain.get("max_pain"):
            print(f"  Max Pain: Rs{max_pain['max_pain']:,.0f} "
                  f"(pull: {max_pain.get('pull_direction', 'N/A')})")
        
    else:
        print("📊 Step 2: Using historical/backtest data...")
        builder = MarketContextBuilder(mode="backtest")
        
        # In backtest mode, build a minimal context
        context = {
            "date": date.today().isoformat(),
            "day_of_week": datetime.now().strftime("%A"),
            "current_time": datetime.now().strftime("%H:%M"),
            "event": today_event,
            "event_multiplier": event_mult,
            "spot": 0,
            "rsi": None, "atr": None,
            "ema_9": None, "ema_21": None,
            "regime": "normal",
            "gap_pct": 0,
            "first_hour": {},
            "pcr": {}, "max_pain": {}, "oi_buildup": {},
            "vix": None, "us_sentiment": None,
        }
    
    print()
    
    # =========================================================================
    # Step 3: Brain Execution (Dynamic Scorer)
    # =========================================================================
    print("🧠 Step 3: Engaging IntelligentBrain (Options Strategy Routing)...")
    brain = IntelligentBrain()
    
    # Pack contextual data from Dhan
    brain_ctx = {
        "india_vix": context.get("vix"),
        "gap_pct": context.get("gap_pct", 0),
        "pcr": context.get("pcr", {}).get("pcr"),
        "max_pain": context.get("max_pain", {}),
        "oi_levels": context.get("oi_levels", {})
    }
    
    # We pass empty df_5d for now as live Lookback is fetched elsewhere,
    # but the Brain handles empty data gracefully.
    import pandas as pd
    thesis = brain.generate_morning_thesis(brain_ctx, pd.DataFrame())
    
    print(f"  System Regime identified as: {thesis['regime']}")
    print(f"  Recommended Strategy Weights:")
    for strategy, weight in thesis["recommended_weights"].items():
        if weight > 1.0:
            print(f"    🟢 {strategy}: {weight}x (Supercharged)")
        elif weight == 0.0:
            print(f"    🔴 {strategy}: {weight}x (BLOCKED)")
        else:
            print(f"    ⚪ {strategy}: {weight}x (Normal)")
    print()
    
    # =========================================================================
    # Step 4: Similar Historical Days
    # =========================================================================
    print("🔍 Step 4: Finding Similar Historical Days...")
    search = SimilaritySearch()
    similarity = search.find_similar_with_outcome(context, top_n=5)
    
    if similarity.get("similar_days"):
        print(f"  Found {similarity['days_analyzed']} similar days:")
        print(f"    Bullish: {similarity['bullish_count']} | "
              f"Bearish: {similarity['bearish_count']} | "
              f"Neutral: {similarity.get('neutral_count', 0)}")
        print(f"    Avg P&L: Rs{similarity['avg_pnl']:,.0f}")
        print(f"    Success Rate: {similarity['success_rate']:.0f}%")
        print(f"    Recommendation: {similarity['recommended_direction']}")
        
        print("  Top matches:")
        for day in similarity["similar_days"][:3]:
            trades_info = f"{day['trade_count']} trades" if day['trade_count'] > 0 else "no trades"
            print(f"    {day['date']} ({day['day_of_week']}): "
                  f"P&L=Rs{day.get('total_pnl', 0):,.0f} | {trades_info} | "
                  f"dist={day['distance']:.3f}")
    else:
        print("  No similar days found in history.")
    print()
    
    # =========================================================================
    # Step 5: Generate Morning Thesis
    # =========================================================================
    print("=" * 60)
    print("📋 MORNING THESIS")
    print("=" * 60)
    
    # Build thesis narrative
    thesis_parts = [thesis["plan"]]
    
    if today_event.get("is_expiry"):
        thesis_parts.append(f"{today_event.get('name', 'Expiry')} — "
                           f"expect max pain pull effect.")
    
    if similarity.get("success_rate", 0) > 60:
        thesis_parts.append(
            f"Similar days were profitable {similarity['success_rate']:.0f}% of the time "
            f"(avg: Rs{similarity['avg_pnl']:,.0f})."
        )
    
    for part in thesis_parts:
        print(f"  {part}")
    print()
    
    # =========================================================================
    # Save Context
    # =========================================================================
    context["brain_thesis"] = thesis
    context["similarity"] = similarity
    context["morning_thesis"] = " ".join(thesis_parts)
    
    # Save to file
    os.makedirs(CONTEXT_DIR, exist_ok=True)
    context_file = os.path.join(CONTEXT_DIR, "market_context.json")
    
    # Filter for serialization
    serializable = {}
    for k, v in context.items():
        if k == "option_chain":
            continue
        try:
            json.dumps(v, default=str)
            serializable[k] = v
        except (TypeError, ValueError):
            serializable[k] = str(v)
    
    with open(context_file, "w") as f:
        json.dump(serializable, f, indent=2, default=str)
    
    print(f"💾 Context saved to {context_file}")
    
    return context


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Jack Pro Morning Prep")
    parser.add_argument("--symbol", default="BANKNIFTY")
    parser.add_argument("--mode", default="auto", choices=["live", "backtest", "auto"])
    args = parser.parse_args()
    
    morning_prep(symbol=args.symbol, mode=args.mode)
