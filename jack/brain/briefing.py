import json
import pandas as pd
from engine.simulator import Simulator
from data.loader import load_all_timeframes, get_lookback
from brain.state import AgentState
import os

class BrainInterface:
    def __init__(self):
        self.simulator = Simulator()
        data_path = os.path.join(self.simulator.base_dir, self.simulator.config["data"]["base_path"])
        self.data = load_all_timeframes(data_path)

    def generate_morning_briefing(self, date_str: str) -> str:
        target_date = pd.Timestamp(date_str)
        daily_df = self.data["1d"]
        
        today_row = daily_df[daily_df["Date"] == target_date]
        if today_row.empty:
            return f"No daily data found for {date_str}"
            
        day_data = {
            "date": target_date,
            "daily": today_row.copy()
        }
        
        for tf in ["2h", "1h", "15m", "5m", "1m"]:
            tf_df = self.data.get(tf, pd.DataFrame())
            if not tf_df.empty:
                day_data[tf] = tf_df[tf_df["Date"] == target_date].copy()
            else:
                day_data[tf] = pd.DataFrame()

        lookback = get_lookback(self.data, target_date, n_days=60)
        
        state = AgentState.load()
        self.simulator.risk_manager.current_capital = state.capital
        self.simulator.risk_manager.peak_capital = state.peak_capital
        
        # Execute run_single_day with briefing_only=True
        result = self.simulator.run_single_day(day_data, lookback, verbose=False, briefing_only=True)
        
        if "error" in result:
            return f"Error computing briefing: {result['error']}"
            
        briefing = result["briefing"]
        
        # Format it nicely for the AI / Human
        output = []
        output.append(f"MORNING BRIEFING: {date_str}")
        output.append(f"Day of Week: {briefing.get('day_of_week')}")
        output.append(f"Current Capital: ₹{briefing.get('capital', 0):,.2f}")
        output.append(f"Drawdown: {briefing.get('drawdown', {}).get('current_drawdown_pct', 0):.2f}%")
        
        output.append("\nMARKET CONDITIONS:")
        output.append(f"Regime: {briefing.get('regime').upper()}")
        
        gap = briefing.get("gap", {})
        output.append(f"Gap: {gap.get('Gap_Type', 'flat')} ({gap.get('Gap_Pct', 0):+.2f}%)")
        
        daily_ind = briefing.get("daily_indicators", {})
        output.append(f"Daily RSI: {daily_ind.get('RSI', 0):.2f}")
        output.append(f"Daily ATR: {daily_ind.get('ATR', 0):.2f}")
        
        streak = briefing.get("streak", {})
        output.append(f"Streak: {streak.get('bull', 0)} Bull / {streak.get('bear', 0)} Bear")
        
        filters = briefing.get("filters", {})
        if filters.get("trade_blocked"):
            output.append("\nWARNING: Trading blocked by pre-market filters.")
            
        output.append(f"\nRAW JSON:\n{json.dumps(briefing, indent=2, default=str)}")
        
        return "\n".join(output)
