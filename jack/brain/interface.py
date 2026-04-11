import os
import pandas as pd
from typing import Dict, Any

from engine.simulator import Simulator
from data.loader import load_all_timeframes, get_lookback
from brain.state import AgentState

class AgentExecutor:
    """Executes the deterministic trading engine for one single day."""
    
    def __init__(self, config_path="config/settings.yaml"):
        # Lazy initialization
        self.simulator = Simulator(config_path)
        self.simulator.risk_manager.current_capital = 0 # Will be synced from state
        
        # Load all data for the session
        data_path = os.path.join(self.simulator.base_dir, self.simulator.config["data"]["base_path"])
        self.data = load_all_timeframes(data_path)

    def _sync_state_to_simulator(self, state: AgentState):
        self.simulator.risk_manager.current_capital = state.capital
        self.simulator.risk_manager.peak_capital = state.peak_capital
        # Also sync open position if any
        self.simulator.risk_manager.open_position = state.open_position
        # Note: If there was a drawdown saved, the risk manager implicitly calculates it from capital and peak.

    def _sync_simulator_to_state(self, state: AgentState):
        state.capital = self.simulator.risk_manager.current_capital
        state.peak_capital = self.simulator.risk_manager.peak_capital
        state.open_position = self.simulator.risk_manager.open_position
        state.drawdown = self.simulator.risk_manager.get_drawdown()

    def _get_day_data(self, date_str: str) -> dict:
        target_date = pd.Timestamp(date_str)
        daily_df = self.data["1d"]
        
        # Get just this day's row
        today_row = daily_df[daily_df["Date"] == target_date]
        if today_row.empty:
            return None
            
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
                
        return day_data

    def get_briefing(self, state: AgentState) -> dict:
        """Just computes the briefing without running trades."""
        # Using the same setup as execute, but modifying simulator to yield early?
        # Actually in Phase 1, run_single_day computes briefing. 
        # For simplicity, we just return the briefing from a dry run or similar.
        pass

    def execute_day(self, state: AgentState) -> Dict[str, Any]:
        """
        Executes a single day based on current date in state.
        
        Args:
            state: The current AgentState
            
        Returns:
            Dict containing daily simulation results
        """
        self._sync_state_to_simulator(state)
        
        day_data = self._get_day_data(state.current_date)
        if not day_data:
            print(f"No data available for {state.current_date}")
            return {"error": "no_data"}
            
        lookback = get_lookback(self.data, pd.Timestamp(state.current_date), n_days=60)
        
        result = self.simulator.run_single_day(day_data, lookback, verbose=True)
        
        if "error" not in result:
            self._sync_simulator_to_state(state)
            
            # Advance date to next trading day
            daily_df = self.data["1d"]
            future_dates = daily_df[daily_df["Date"] > pd.Timestamp(state.current_date)]["Date"]
            if not future_dates.empty:
                next_date = future_dates.min().strftime("%Y-%m-%d")
                state.current_date = next_date
            else:
                print("Reached end of data.")
                
            state.save()
            
        return result
