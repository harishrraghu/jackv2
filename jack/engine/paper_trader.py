"""
Paper Trading Mode.

Connects to a real-time data feed (placeholder) and runs Jack's simulation
engine progressively. Generates signals and logs trades hypothetically.
"""

from typing import Callable
import pandas as pd

from engine.simulator import Simulator


class PaperTrader:
    """Live paper trading manager."""

    def __init__(self, simulator: Simulator):
        self.simulator = simulator
        self.lookback_data = {}  # Store previous N days of context
        self.current_day_data = {"15m": pd.DataFrame(), "1h": pd.DataFrame(), "1d": pd.DataFrame()}

    def setup_lookback(self, data: dict):
        """Pre-load context data before paper trading starts."""
        self.lookback_data = data

    def on_market_open(self, date: pd.Timestamp):
        """Called at 09:15 daily."""
        self.current_day_data["date"] = date
        self.simulator.risk_manager.reset_daily()
        self.simulator.scorer.clear_log()
        print(f"Paper trading active for {date.strftime('%Y-%m-%d')}")

    def on_new_candle(self, timeframe: str, candle: dict):
        """
        Called when a new candle closes.
        """
        # Append to our daily tracking data
        df = self.current_day_data.get(timeframe, pd.DataFrame())
        df = pd.concat([df, pd.DataFrame([candle])], ignore_index=True)
        self.current_day_data[timeframe] = df

    def run_cycle(self):
        """
        Run the decision sequence simulating the current state of intraday data.
        Normally, this relies on on_new_candle having updated current_day_data.
        """
        if not self.lookback_data:
            print("Cannot run cycle without lookback data.")
            return

        # Uses the simulator's single day execution functionality internally
        # which accepts intraday data build-up
        result = self.simulator.run_single_day(
            day_data=self.current_day_data,
            lookback=self.lookback_data,
            verbose=True,
            briefing_only=False
        )
        return result
