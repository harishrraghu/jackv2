"""
Strategy: IV Expansion Ride.

Buys options when IV is historically cheap and expected to expand, providing twin engines of profit (Direction + Vollatility).
"""

from typing import Optional
from strategies.base import Strategy, TradeSignal, ExitSignal

class IVExpansionRide(Strategy):
    """Buy options when IV is low and about to expand."""

    def __init__(self, params: dict = None):
        default_params = {
            "max_iv_ratio": 0.9,     # VRP ratio must be < this
            "adx_min": 20,           # Needs some directional movement potential
            "stop_pct": 25,          # Stop loss 25% of premium
            "target_pct": 40,        # Target 40% of premium
        }
        if params:
            default_params.update(params)

        super().__init__(name="iv_expansion_ride", params=default_params)
        self.required_indicators = ["iv_edge", "greeks_momentum"]
        self.eligible_timeframes = ["09:30-14:00"] # Not too late in the day

    def check_entry(
        self,
        day_data: dict,
        lookback: dict,
        indicators: dict,
        current_time: str,
        filters: dict,
        diagnostics: dict = None,
    ) -> Optional[TradeSignal]:
        
        iv_edge = indicators.get("iv_edge", {})
        vrp_ratio = iv_edge.get("vrp_ratio", 1.0)
        
        # Condition 1: Options must be cheap
        if vrp_ratio >= self.params["max_iv_ratio"]:
            if diagnostics is not None: diagnostics["reason_skipped"] = f"iv_not_cheap_enough: {vrp_ratio:.2f}"
            return None
            
        greeks = indicators.get("greeks_momentum", {})
        if not greeks.get("is_favorable", False):
            if diagnostics is not None: diagnostics["reason_skipped"] = f"poor_greeks_environment"
            return None
            
        # Condition 2: Directional confirmation (using Regimes or ADX)
        daily = indicators.get("daily", {})
        adx = daily.get("ADX", 0)
        regime = daily.get("Regime", "normal")
        
        if adx < self.params["adx_min"] and regime not in ["squeeze"]:
            if diagnostics is not None: diagnostics["reason_skipped"] = f"no_trend_or_squeeze: adx={adx}"
            return None
            
        # Determine direction based on EMA or VWAP
        current_price = indicators.get("current_price", 0)
        vwap = indicators.get("vwap", 0)
        direction = "LONG" if current_price > vwap else "SHORT"

        if diagnostics is not None:
            diagnostics["base_condition_met"] = True
            diagnostics["signal_generated"] = True
            diagnostics["reason_skipped"] = None

        return TradeSignal(
            strategy_name=self.name,
            direction=direction,
            entry_price=current_price,
            stop_loss=current_price * 0.99 if direction=="LONG" else current_price * 1.01, # Proxy, will be managed via premium
            target=current_price * 1.02 if direction=="LONG" else current_price * 0.98,
            confidence=0.8,
            reason=f"IV Expansion Ride: VRP={vrp_ratio:.2f}, Regime={regime}",
            metadata={
                "vrp_ratio": vrp_ratio,
                "strategy_type": "options_buyer"
            }
        )

    def check_exit(self, position: dict, day_data: dict, current_time: str, current_price: float) -> ExitSignal:
        # Time exit
        if current_time >= "15:00":
            return ExitSignal(True, current_price, "time_exit")
            
        # Trailing stops handled by position manager usually.
        direction = position.get("direction", "LONG")
        # In actual execution, this would trigger on Option Premium %, simulated loosely here.
        return ExitSignal(False, current_price, "hold")

    def score(self, signal: TradeSignal, filters: dict) -> float:
        return signal.confidence
