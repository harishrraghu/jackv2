"""
Strategy: Theta Harvester.

Sells OTM strangles on Bank Nifty weekly expiry days (Thursday) in calm markets.
"""

from typing import Optional
from strategies.base import Strategy, TradeSignal, ExitSignal
from engine.options import StrikeSelector


class ThetaHarvest(Strategy):
    """Sell OTM strangles on Expiry days."""

    def __init__(self, params: dict = None):
        default_params = {
            "atr_otm_multiplier": 1.5,
            "stop_loss_multiplier": 2.0, # Stop loss if premium doubles
        }
        if params:
            default_params.update(params)

        super().__init__(name="theta_harvest", params=default_params)
        self.required_indicators = ["atr"]
        self.eligible_timeframes = ["09:30"]

    def check_entry(
        self,
        day_data: dict,
        lookback: dict,
        indicators: dict,
        current_time: str,
        filters: dict,
        diagnostics: dict = None,
    ) -> Optional[TradeSignal]:
        """
        Check entry conditions.

        DISABLED: Options pricing not integrated — no live premium data.
        Re-enable once real-time options chain is connected.
        """
        # DISABLED: Options pricing not integrated — no live premium data available.
        # Re-enable once real-time options chain is connected.
        if diagnostics is not None:
            diagnostics["reason_skipped"] = "strategy_disabled_options_not_integrated"
        return None

    def check_exit(
        self,
        position: dict,
        day_data: dict,
        current_time: str,
        current_price: float,
    ) -> ExitSignal:
        """Exit at 13:00 or stop."""
        if current_time >= "13:00":
            return ExitSignal(True, current_price, "time_exit")

        # In a real engine, we'd price the options here and check if premium doubled.
        # As a fallback, we check if spot moved wildly
        atr = position.get("metadata", {}).get("atr", 100)
        entry_price = position.get("entry_price", current_price)

        move = abs(current_price - entry_price)
        if move > atr * 1.5:
            return ExitSignal(True, current_price, "stop_hit_spot_moved")

        return ExitSignal(False, current_price, "hold")

    def score(self, signal: TradeSignal, filters: dict) -> float:
        return signal.confidence
