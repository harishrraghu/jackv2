"""
Strategy: Delta Scalp.

Quick execution scaling strategy capitalizing on max gamma momentum.
"""

from typing import Optional
from strategies.base import Strategy, TradeSignal, ExitSignal

class DeltaScalp(Strategy):
    """Gamma-optimized scalp."""

    def __init__(self, params: dict = None):
        default_params = {
            "max_hold_time_mins": 30
        }
        if params:
            default_params.update(params)

        super().__init__(name="delta_scalp", params=default_params)
        self.required_indicators = ["greeks_momentum"]
        self.eligible_timeframes = ["09:45-15:00"]

    def check_entry(
        self,
        day_data: dict,
        lookback: dict,
        indicators: dict,
        current_time: str,
        filters: dict,
        diagnostics: dict = None,
    ) -> Optional[TradeSignal]:
        
        greeks = indicators.get("greeks_momentum", {})
        if greeks.get("signal") != "GAMMA_SWEET_SPOT":
            if diagnostics is not None: diagnostics["reason_skipped"] = "not_in_gamma_sweet_spot"
            return None
            
        current_price = indicators.get("current_price", 0)
        daily = indicators.get("daily", {})
        rsi = indicators.get("rsi_5m", 50)
        
        direction = None
        if rsi > 60:
            direction = "LONG"
        elif rsi < 40:
            direction = "SHORT"
            
        if not direction:
            if diagnostics is not None: diagnostics["reason_skipped"] = "no_momentum"
            return None

        if diagnostics is not None:
            diagnostics["base_condition_met"] = True
            diagnostics["signal_generated"] = True
            diagnostics["reason_skipped"] = None

        return TradeSignal(
            strategy_name=self.name,
            direction=direction,
            entry_price=current_price,
            stop_loss=current_price * 0.998 if direction=="LONG" else current_price * 1.002,
            target=current_price * 1.004 if direction=="LONG" else current_price * 0.996,
            confidence=0.6,
            reason=f"Delta Scalp {direction} with Gamma Sweet Spot",
            metadata={"strategy_type": "scalp"}
        )

    def check_exit(self, position: dict, day_data: dict, current_time: str, current_price: float) -> ExitSignal:
        if current_time >= "15:20":
            return ExitSignal(True, current_price, "time_exit")
        return ExitSignal(False, current_price, "hold")

    def score(self, signal: TradeSignal, filters: dict) -> float:
        return signal.confidence
